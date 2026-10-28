from dataclasses import replace
from pathlib import Path
from threading import Event
import unittest

from model_automation.engine import RuntimeContext, StepEngine, StepResult
from model_automation.models import Preset, Step
from model_automation.registry import StepDefinition, StepRegistry


class StepEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[str] = []
        self.logs: list[str] = []
        self.registry = StepRegistry()
        self.registry.register(
            StepDefinition(
                key="pass",
                label="Pass",
                fields=(),
                runner=self._pass,
            )
        )
        self.registry.register(
            StepDefinition(
                key="fail",
                label="Fail",
                fields=(),
                runner=self._fail,
                can_fail=True,
            )
        )
        self.context = RuntimeContext(
            device=object(),
            template_dir=Path("templates"),
            stop_event=Event(),
            log=self.logs.append,
        )

    def _pass(self, step: Step, _context: RuntimeContext) -> StepResult:
        self.calls.append(step.name)
        return StepResult(True, "ok")

    def _fail(self, step: Step, _context: RuntimeContext) -> StepResult:
        self.calls.append(step.name)
        return StepResult(False, "not found")

    def test_continue_runs_next_step_after_failure(self) -> None:
        preset = Preset(
            name="continue",
            steps=[
                Step(name="optional", kind="fail", on_failure="continue"),
                Step(name="next", kind="pass"),
            ],
        )

        report = StepEngine(self.registry).run(preset, self.context)

        self.assertEqual("completed", report.status)
        self.assertEqual(["optional", "next"], self.calls)
        self.assertTrue(any("跳过" in message for message in self.logs))

    def test_stop_prevents_later_steps_after_failure(self) -> None:
        preset = Preset(
            name="stop",
            steps=[
                Step(name="required", kind="fail", on_failure="stop"),
                Step(name="never", kind="pass"),
            ],
        )

        report = StepEngine(self.registry).run(preset, self.context)

        self.assertEqual("failed", report.status)
        self.assertEqual(["required"], self.calls)

    def test_disabled_steps_are_not_executed(self) -> None:
        preset = Preset(
            name="disabled",
            steps=[
                Step(name="off", kind="pass", enabled=False),
                Step(name="on", kind="pass"),
            ],
        )

        report = StepEngine(self.registry).run(preset, self.context)

        self.assertEqual("completed", report.status)
        self.assertEqual(["on"], self.calls)

    def test_finite_loop_runs_whole_preset_requested_number_of_times(self) -> None:
        preset = Preset(
            name="repeat",
            loop_count=3,
            steps=[Step(name="action", kind="pass")],
        )

        report = StepEngine(self.registry).run(preset, self.context)

        self.assertEqual("completed", report.status)
        self.assertEqual(["action", "action", "action"], self.calls)

    def test_infinite_loop_stops_on_unhandled_failure(self) -> None:
        attempts = 0

        def eventual_failure(
            _step: Step, _context: RuntimeContext
        ) -> StepResult:
            nonlocal attempts
            attempts += 1
            return StepResult(attempts < 3, "failed" if attempts == 3 else "ok")

        registry = StepRegistry()
        registry.register(
            StepDefinition(
                key="eventual",
                label="Eventual",
                fields=(),
                runner=eventual_failure,
            )
        )
        preset = Preset(
            name="infinite",
            loop_count=0,
            steps=[Step(name="action", kind="eventual")],
        )

        report = StepEngine(registry).run(preset, self.context)

        self.assertEqual("failed", report.status)
        self.assertEqual(3, attempts)

    def test_empty_infinite_preset_fails_without_busy_looping(self) -> None:
        preset = Preset(name="empty", loop_count=0)

        report = StepEngine(self.registry).run(preset, self.context)

        self.assertEqual("failed", report.status)
        self.assertIn("没有启用", report.message)

    def test_dependent_runs_when_prerequisite_succeeded(self) -> None:
        prerequisite = Step(name="before", kind="pass")
        preset = Preset(
            name="linked",
            steps=[
                prerequisite,
                Step(name="after", kind="pass", depends_on=[prerequisite.id]),
            ],
        )

        report = StepEngine(self.registry).run(preset, self.context)

        self.assertEqual("completed", report.status)
        self.assertEqual(["before", "after"], self.calls)

    def test_dependent_skipped_when_prerequisite_continued(self) -> None:
        prerequisite = Step(name="before", kind="fail", on_failure="continue")
        preset = Preset(
            name="linked",
            steps=[
                prerequisite,
                Step(name="after", kind="pass", depends_on=[prerequisite.id]),
            ],
        )

        report = StepEngine(self.registry).run(preset, self.context)

        self.assertEqual("completed", report.status)
        self.assertEqual(["before"], self.calls)
        self.assertTrue(any("前置步骤未执行" in message for message in self.logs))

    def test_skip_propagates_through_dependency_chain(self) -> None:
        first = Step(name="first", kind="fail", on_failure="continue")
        second = Step(name="second", kind="pass", depends_on=[first.id])
        preset = Preset(
            name="chain",
            steps=[
                first,
                second,
                Step(name="third", kind="pass", depends_on=[second.id]),
            ],
        )

        report = StepEngine(self.registry).run(preset, self.context)

        self.assertEqual("completed", report.status)
        self.assertEqual(["first"], self.calls)

    def test_disabled_prerequisite_skips_dependent(self) -> None:
        prerequisite = Step(name="off", kind="pass", enabled=False)
        preset = Preset(
            name="linked",
            steps=[
                prerequisite,
                Step(name="after", kind="pass", depends_on=[prerequisite.id]),
            ],
        )

        report = StepEngine(self.registry).run(preset, self.context)

        self.assertEqual("completed", report.status)
        self.assertEqual([], self.calls)

    def test_unknown_dependency_skips_dependent(self) -> None:
        preset = Preset(
            name="stale",
            steps=[Step(name="after", kind="pass", depends_on=["ghost"])],
        )

        report = StepEngine(self.registry).run(preset, self.context)

        self.assertEqual("completed", report.status)
        self.assertEqual([], self.calls)

    def test_dependency_state_resets_between_loop_cycles(self) -> None:
        attempts = 0

        def fail_first_then_succeed(
            step: Step, _context: RuntimeContext
        ) -> StepResult:
            nonlocal attempts
            self.calls.append(step.name)
            attempts += 1
            return StepResult(attempts > 1, "failed once" if attempts == 1 else "ok")

        registry = StepRegistry()
        registry.register(
            StepDefinition(
                key="pass",
                label="Pass",
                fields=(),
                runner=self._pass,
            )
        )
        registry.register(
            StepDefinition(
                key="eventual",
                label="Eventual",
                fields=(),
                runner=fail_first_then_succeed,
            )
        )
        prerequisite = Step(name="flaky", kind="eventual", on_failure="continue")
        preset = Preset(
            name="reset",
            loop_count=2,
            steps=[
                prerequisite,
                Step(name="after", kind="pass", depends_on=[prerequisite.id]),
            ],
        )

        report = StepEngine(registry).run(preset, self.context)

        self.assertEqual("completed", report.status)
        self.assertEqual(["flaky", "flaky", "after"], self.calls)


    def test_restart_skips_remaining_steps_and_counts_a_cycle(self) -> None:
        def restart_runner(
            _step: Step, _context: RuntimeContext
        ) -> StepResult:
            self.calls.append("trigger")
            return StepResult(True, "branch done", restart=True)

        registry = StepRegistry()
        registry.register(
            StepDefinition(
                key="pass",
                label="Pass",
                fields=(),
                runner=self._pass,
            )
        )
        registry.register(
            StepDefinition(
                key="restart",
                label="Restart",
                fields=(),
                runner=restart_runner,
            )
        )
        preset = Preset(
            name="restart",
            loop_count=2,
            steps=[
                Step(name="first", kind="pass"),
                Step(name="trigger", kind="restart"),
                Step(name="after", kind="pass"),
            ],
        )

        report = StepEngine(registry).run(preset, self.context)

        self.assertEqual("completed", report.status)
        self.assertEqual(["first", "trigger", "first", "trigger"], self.calls)
        self.assertNotIn("after", self.calls)
        self.assertTrue(any("开始下一轮" in message for message in self.logs))

    def test_restart_on_finite_loop_terminates_normally(self) -> None:
        def restart_runner(
            _step: Step, _context: RuntimeContext
        ) -> StepResult:
            self.calls.append("trigger")
            return StepResult(True, "branch done", restart=True)

        registry = StepRegistry()
        registry.register(
            StepDefinition(
                key="pass",
                label="Pass",
                fields=(),
                runner=self._pass,
            )
        )
        registry.register(
            StepDefinition(
                key="restart",
                label="Restart",
                fields=(),
                runner=restart_runner,
            )
        )
        preset = Preset(
            name="once",
            loop_count=1,
            steps=[
                Step(name="first", kind="pass"),
                Step(name="trigger", kind="restart"),
            ],
        )

        report = StepEngine(registry).run(preset, self.context)

        self.assertEqual("completed", report.status)
        self.assertEqual(["first", "trigger"], self.calls)


class ReturnJumpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[str] = []
        self.logs: list[str] = []
        self.registry = StepRegistry()
        self.registry.register(
            StepDefinition(
                key="pass",
                label="Pass",
                fields=(),
                runner=self._pass,
            )
        )
        self.context = RuntimeContext(
            device=object(),
            template_dir=Path("templates"),
            stop_event=Event(),
            log=self.logs.append,
        )

    def _pass(self, step: Step, _context: RuntimeContext) -> StepResult:
        self.calls.append(step.name)
        return StepResult(True, "ok")

    def test_return_loops_back_until_target_fails(self) -> None:
        counts = {"A": 0}

        def gate(step: Step, _context: RuntimeContext) -> StepResult:
            self.calls.append(step.name)
            if step.name == "A":
                counts["A"] += 1
                return StepResult(counts["A"] < 4, "再试" if counts["A"] < 4 else "识别失败")
            return StepResult(True, "ok")

        registry = StepRegistry()
        registry.register(
            StepDefinition(
                key="gate",
                label="Gate",
                fields=(),
                runner=gate,
                can_fail=True,
            )
        )
        a = Step(name="A", kind="gate", on_failure="stop")
        b = Step(name="B", kind="gate")
        b.params["return_to"] = a.id
        c = Step(name="C", kind="gate")
        preset = Preset(name="return", steps=[a, b, c])

        report = StepEngine(registry).run(preset, self.context)

        self.assertEqual("failed", report.status)
        self.assertEqual(["A", "B", "A", "B", "A", "B", "A"], self.calls)
        self.assertNotIn("C", self.calls)
        self.assertTrue(any("返回步骤“A”" in line for line in self.logs))

    def test_return_jumps_from_later_step_back_to_earlier_target(self) -> None:
        counts = {"A": 0}

        def gate(step: Step, _context: RuntimeContext) -> StepResult:
            self.calls.append(step.name)
            if step.name == "A":
                counts["A"] += 1
                return StepResult(counts["A"] < 2, "识别失败")
            return StepResult(True, "ok")

        registry = StepRegistry()
        registry.register(
            StepDefinition(
                key="gate",
                label="Gate",
                fields=(),
                runner=gate,
                can_fail=True,
            )
        )
        a = Step(name="A", kind="gate", on_failure="stop")
        b = Step(name="B", kind="gate")
        c = Step(name="C", kind="gate")
        c.params["return_to"] = a.id
        preset = Preset(name="return", steps=[a, b, c])

        report = StepEngine(registry).run(preset, self.context)

        self.assertEqual("failed", report.status)
        self.assertEqual(["A", "B", "C", "A"], self.calls)
        self.assertTrue(any("返回步骤“A”" in line for line in self.logs))

    def test_forward_self_or_unknown_return_target_is_ignored(self) -> None:
        a = Step(name="A", kind="pass")
        b = Step(name="B", kind="pass")
        b.params["return_to"] = b.id
        d = Step(name="D", kind="pass")
        c = Step(name="C", kind="pass")
        c.params["return_to"] = d.id
        d.params["return_to"] = "ghost"
        preset = Preset(name="return", steps=[a, b, c, d])

        report = StepEngine(self.registry).run(preset, self.context)

        self.assertEqual("completed", report.status)
        self.assertEqual(["A", "B", "C", "D"], self.calls)
        self.assertFalse(any("返回步骤" in line for line in self.logs))

    def test_disabled_return_target_does_not_jump(self) -> None:
        a = Step(name="A", kind="pass", enabled=False)
        b = Step(name="B", kind="pass")
        b.params["return_to"] = a.id
        preset = Preset(name="return", steps=[a, b])

        report = StepEngine(self.registry).run(preset, self.context)

        self.assertEqual("completed", report.status)
        self.assertEqual(["B"], self.calls)


class DependencyRecoveryTests(unittest.TestCase):
    def test_backward_jump_recovers_failed_and_transitively_skipped_steps(self):
        calls = []
        attempts = 0
        jumps = 0
        first = Step(name="first", kind="action", on_failure="continue")
        second = Step(name="second", kind="action", depends_on=[first.id])
        third = Step(name="third", kind="action", depends_on=[second.id])

        def runner(step, _context):
            nonlocal attempts, jumps
            calls.append(step.name)
            if step.name == "first":
                attempts += 1
                return StepResult(attempts > 1)
            if step.name == "jump":
                jumps += 1
                if jumps == 1:
                    return StepResult(True, jump_to=first.id)
            return StepResult(True)

        registry = StepRegistry()
        registry.register(StepDefinition("action", "Action", (), runner))
        context = RuntimeContext(object(), Path("templates"), Event(), lambda _: None)
        preset = Preset(name="recovery", steps=[first, second, third,
                                                Step(name="jump", kind="action")])
        report = StepEngine(registry).run(preset, context)
        self.assertEqual("completed", report.status)
        self.assertEqual(["first", "jump", "first", "second", "third", "jump"], calls)


class StructuredEventTests(unittest.TestCase):
    def context(self, events, **kwargs):
        return RuntimeContext(object(), Path("templates"), Event(), lambda _: None,
                              event=events.append, **kwargs)

    def test_success_without_message_and_unknown_type_have_terminal_events(self):
        registry = StepRegistry()
        registry.register(StepDefinition("ok", "OK", (), lambda *_: StepResult(True)))
        good = Step(name="same", kind="ok")
        bad = Step(name="same", kind="unknown")
        events = []
        report = StepEngine(registry).run(Preset(name="events", steps=[good, bad]), self.context(events))
        self.assertEqual("failed", report.status)
        states = [(e["data"]["step_id"], e["data"]["state"]) for e in events if e["type"] == "step"]
        self.assertEqual([(good.id, "running"), (good.id, "done"),
                          (bad.id, "running"), (bad.id, "failed")], states)
        self.assertEqual("enter", events[0]["data"]["action"])
        self.assertEqual("exit", events[-1]["data"]["action"])
        self.assertEqual(1, len({e["data"]["run_id"] for e in events}))

    def test_nested_replace_inherits_callback_and_preserves_parent_frame(self):
        from dataclasses import replace
        registry = StepRegistry()
        child = Preset(name="duplicate", steps=[Step(name="event", kind="ok")])
        registry.register(StepDefinition("ok", "OK", (), lambda *_: StepResult(True)))
        def nested(_step, context):
            result = context.engine.run(child, replace(context, allow_external_jump=True))
            return StepResult(result.status == "completed")
        registry.register(StepDefinition("nested", "Nested", (), nested))
        parent = Step(name="event", kind="nested")
        events = []
        engine = StepEngine(registry)
        engine.run(Preset(name="duplicate", steps=[parent]), self.context(events, engine=engine))
        enters = [e["data"] for e in events if e["type"] == "frame" and e["data"]["action"] == "enter"]
        self.assertEqual(enters[0]["frame_id"], enters[1]["parent_frame_id"])
        self.assertEqual(parent.id, enters[1]["parent_step_id"])
        self.assertNotEqual(enters[0]["frame_id"], enters[1]["frame_id"])
        self.assertEqual(enters[0]["run_id"], enters[1]["run_id"])

    def test_empty_stop_and_exception_always_close_frames(self):
        registry = StepRegistry()
        def stop(_step, context):
            context.stop_event.set()
            return StepResult(True)
        def fail(*_):
            raise ValueError("boom")
        registry.register(StepDefinition("stop", "Stop", (), stop))
        registry.register(StepDefinition("fail", "Fail", (), fail))
        for preset, status in [(Preset(name="events", ), "completed"), (Preset(name="events", loop_count=0), "failed"),
                               (Preset(name="events", steps=[Step(name="event", kind="stop")]), "stopped"),
                               (Preset(name="events", steps=[Step(name="event", kind="fail")]), "failed")]:
            with self.subTest(status=status):
                events = []
                report = StepEngine(registry).run(preset, self.context(events))
                self.assertEqual(status, report.status)
                self.assertEqual("exit", events[-1]["data"]["action"])
                self.assertEqual(status, events[-1]["data"]["status"])

    def test_external_jump_emits_target_before_frame_exit(self):
        registry = StepRegistry()
        registry.register(StepDefinition("jump", "Jump", (), lambda *_: StepResult(True, jump_to="outside")))
        events = []
        report = StepEngine(registry).run(Preset(name="events", steps=[Step(name="event", kind="jump")]),
                                          self.context(events, allow_external_jump=True))
        self.assertEqual("outside", report.jump_to)
        jumps = [e["data"] for e in events if e["type"] == "jump"]
        self.assertEqual("outside", jumps[0]["target_step_id"])
        self.assertTrue(jumps[0]["external"])
        self.assertEqual("exit", events[-1]["data"]["action"])


class StartStepTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[str] = []
        self.logs: list[str] = []
        self.jumped = False
        self.target_id = ""
        self.child = Preset(
            name="child", steps=[Step(name="child-first", kind="pass")]
        )
        self.registry = StepRegistry()
        self.registry.register(
            StepDefinition(key="pass", label="Pass", fields=(), runner=self._pass)
        )
        self.registry.register(
            StepDefinition(
                key="jump_once", label="Jump once", fields=(), runner=self._jump_once
            )
        )
        self.registry.register(
            StepDefinition(
                key="nested", label="Nested", fields=(), runner=self._nested
            )
        )
        self.registry.register(
            StepDefinition(
                key="restart", label="Restart", fields=(), runner=self._restart
            )
        )
        self.context = RuntimeContext(
            device=object(),
            template_dir=Path("templates"),
            stop_event=Event(),
            log=self.logs.append,
        )

    def _pass(self, step: Step, _context: RuntimeContext) -> StepResult:
        self.calls.append(step.name)
        return StepResult(True, "ok")

    def _jump_once(self, step: Step, _context: RuntimeContext) -> StepResult:
        self.calls.append(step.name)
        if step.name == "third" and not self.jumped:
            self.jumped = True
            return StepResult(True, jump_to=self.target_id)
        return StepResult(True, "ok")

    def _nested(self, step: Step, context: RuntimeContext) -> StepResult:
        self.calls.append(step.name)
        report = context.engine.run(self.child, replace(context))
        return StepResult(report.status == "completed", report.message)

    def _restart(self, step: Step, _context: RuntimeContext) -> StepResult:
        self.calls.append(step.name)
        return StepResult(True, "restart", restart=True)

    def test_start_step_runs_suffix_and_keeps_original_step_indices(self) -> None:
        first = Step(name="first", kind="pass")
        second = Step(name="second", kind="pass")
        third = Step(name="third", kind="pass")
        events = []
        context = replace(
            self.context, start_step_id=second.id, event=events.append
        )

        report = StepEngine(self.registry).run(
            Preset(name="suffix", steps=[first, second, third]), context
        )

        self.assertEqual("completed", report.status)
        self.assertEqual(["second", "third"], self.calls)
        running = [
            event["data"]
            for event in events
            if event["type"] == "step" and event["data"]["state"] == "running"
        ]
        self.assertEqual([2, 3], [item["step_index"] for item in running])

    def test_start_step_treats_prior_dependencies_as_satisfied(self) -> None:
        first = Step(name="first", kind="pass")
        second = Step(name="second", kind="pass", depends_on=[first.id])

        report = StepEngine(self.registry).run(
            Preset(name="dependent", steps=[first, second]),
            replace(self.context, start_step_id=second.id),
        )

        self.assertEqual("completed", report.status)
        self.assertEqual(["second"], self.calls)

    def test_start_step_treats_disabled_prior_dependency_as_satisfied(self) -> None:
        first = Step(name="first", kind="pass", enabled=False)
        second = Step(name="second", kind="pass", depends_on=[first.id])

        report = StepEngine(self.registry).run(
            Preset(name="dependent", steps=[first, second]),
            replace(self.context, start_step_id=second.id),
        )

        self.assertEqual("completed", report.status)
        self.assertEqual(["second"], self.calls)

    def test_start_step_runs_suffix_once_for_finite_and_infinite_presets(self) -> None:
        first = Step(name="first", kind="pass")
        second = Step(name="second", kind="pass")
        third = Step(name="third", kind="pass")
        for loop_count in (3, 0):
            with self.subTest(loop_count=loop_count):
                self.calls.clear()
                report = StepEngine(self.registry).run(
                    Preset(
                        name="looped",
                        loop_count=loop_count,
                        steps=[first, second, third],
                    ),
                    replace(self.context, start_step_id=second.id),
                )
                self.assertEqual("completed", report.status)
                self.assertEqual(["second", "third"], self.calls)

    def test_start_step_ignores_return_target_before_start(self) -> None:
        first = Step(name="first", kind="pass")
        second = Step(name="second", kind="pass")
        second.params["return_to"] = first.id

        report = StepEngine(self.registry).run(
            Preset(name="return", steps=[first, second]),
            replace(self.context, start_step_id=second.id),
        )

        self.assertEqual("completed", report.status)
        self.assertEqual(["second"], self.calls)
        self.assertTrue(
            any("起点之前的返回目标" in message for message in self.logs)
        )

    def test_start_step_allows_return_target_inside_suffix(self) -> None:
        first = Step(name="first", kind="pass")
        second = Step(name="second", kind="pass")
        third = Step(name="third", kind="jump_once")
        self.target_id = second.id

        report = StepEngine(self.registry).run(
            Preset(name="return", steps=[first, second, third]),
            replace(self.context, start_step_id=second.id),
        )

        self.assertEqual("completed", report.status)
        self.assertEqual(["second", "third", "second", "third"], self.calls)

    def test_start_step_ends_after_restart_without_another_cycle(self) -> None:
        first = Step(name="first", kind="pass")
        trigger = Step(name="trigger", kind="restart")
        after = Step(name="after", kind="pass")

        report = StepEngine(self.registry).run(
            Preset(name="restart", loop_count=0, steps=[first, trigger, after]),
            replace(self.context, start_step_id=trigger.id),
        )

        self.assertEqual("completed", report.status)
        self.assertEqual(["trigger"], self.calls)
        self.assertTrue(any("后缀执行结束" in message for message in self.logs))
        self.assertFalse(any("开始下一轮循环" in message for message in self.logs))

    def test_start_step_rejects_unknown_or_disabled_start(self) -> None:
        first = Step(name="first", kind="pass", enabled=False)
        second = Step(name="second", kind="pass")
        preset = Preset(name="invalid", steps=[first, second])
        engine = StepEngine(self.registry)

        for start_id in ("missing", first.id):
            with self.subTest(start_id=start_id):
                self.calls.clear()
                report = engine.run(
                    preset, replace(self.context, start_step_id=start_id)
                )
                self.assertEqual("failed", report.status)
                self.assertIn("起始步骤", report.message)

    def test_start_step_does_not_leak_into_nested_preset(self) -> None:
        prefix = Step(name="prefix", kind="pass")
        nested = Step(name="nested", kind="nested")
        engine = StepEngine(self.registry)

        report = engine.run(
            Preset(name="parent", steps=[prefix, nested]),
            replace(
                self.context, start_step_id=nested.id, engine=engine
            ),
        )

        self.assertEqual("completed", report.status)
        self.assertEqual(["nested", "child-first"], self.calls)


if __name__ == "__main__":
    unittest.main()
