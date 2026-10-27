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


if __name__ == "__main__":
    unittest.main()
