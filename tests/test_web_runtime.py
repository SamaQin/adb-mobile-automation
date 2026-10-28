import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, local, get_ident
from unittest.mock import patch
import time
import unittest

import numpy as np

from model_automation.config import ConfigStore
from model_automation.engine import ExecutionReport, RuntimeContext, StepResult
from model_automation.registry import StepDefinition, StepRegistry
from model_automation.models import AppConfig, Preset, Step
from web_server.runtime import RuntimeConflict, RuntimeManager, _LogParser


class FakeDevice:
    def __init__(self) -> None:
        self.screen = np.zeros((60, 100, 3), dtype=np.uint8)

    def state(self) -> str:
        return "device"

    def screenshot(self) -> np.ndarray:
        return self.screen.copy()

    def screen_resolution(self) -> tuple[int, int]:
        return 100, 60

    def tap(self, _x: int, _y: int) -> None:
        pass

    def swipe(self, _x1: int, _y1: int, _x2: int, _y2: int, _duration: int) -> None:
        pass


class SnapshotEngine:
    def __init__(self, started: Event, release: Event) -> None:
        self.started = started
        self.release = release
        self.sub_name: str | None = None

    def run(self, _preset: Preset, context) -> ExecutionReport:
        self.started.set()
        self.release.wait(2)
        self.sub_name = next(
            preset.name for preset in context.presets.values() if preset.name != "root"
        )
        return ExecutionReport("completed", "done")


class RuntimeManagerTests(unittest.TestCase):
    @staticmethod
    def wait_until_idle(manager: RuntimeManager) -> None:
        deadline = time.monotonic() + 2
        while manager.is_running and time.monotonic() < deadline:
            time.sleep(0.01)

    def test_acceleration_is_initialized_on_the_execution_thread(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = ConfigStore(root / 'config.json', root / 'templates')
            preset = Preset(name='test', steps=[Step(name='wait', kind='wait')])
            store.save(AppConfig(presets=[preset], selected_preset_id=preset.id, acceleration='gpu'))
            context = local()
            observed = []
            caller = get_ident()

            def apply(mode):
                context.mode = mode
                return mode

            class Engine:
                def run(self, _preset, _context):
                    observed.append((get_ident(), getattr(context, 'mode', None)))
                    return ExecutionReport('completed', 'done')

            manager = RuntimeManager(store, FakeDevice(), engine_factory=lambda _: Engine())
            with patch('web_server.runtime.set_acceleration', side_effect=apply):
                manager.start(preset.id)
                self.wait_until_idle(manager)
            self.assertEqual(1, len(observed))
            self.assertNotEqual(caller, observed[0][0])
            self.assertEqual('gpu', observed[0][1])
            self.assertEqual('completed', manager.status()['last_status'])

    def test_runtime_locks_mutations_and_snapshots_every_preset(self) -> None:
        with TemporaryDirectory() as directory:
            root_path = Path(directory)
            store = ConfigStore(root_path / "config.json", root_path / "templates")
            sub = Preset(name="sub")
            root = Preset(name="root", steps=[Step(name="wait", kind="wait")])
            store.save(AppConfig(presets=[root, sub], selected_preset_id=root.id))
            started = Event()
            release = Event()
            engine = SnapshotEngine(started, release)
            manager = RuntimeManager(
                store,
                FakeDevice(),
                engine_factory=lambda _registry: engine,
            )

            status = manager.start(root.id)
            self.assertEqual("running", status["state"])
            self.assertTrue(started.wait(1))
            with self.assertRaises(RuntimeConflict):
                manager.ensure_mutable()

            changed = store.load()
            changed.presets[1].name = "changed"
            store.save(changed)
            release.set()
            self.wait_until_idle(manager)

            self.assertEqual("sub", engine.sub_name)
            self.assertEqual("completed", manager.status()["last_status"])

    def test_event_buffer_is_bounded(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manager = RuntimeManager(
                ConfigStore(root / "config.json", root / "templates"),
                FakeDevice(),
                event_limit=200,
            )
            for index in range(205):
                manager.publish_device({"index": index})

            events = manager.events()

            self.assertEqual(200, len(events))
            self.assertEqual(5, events[0]["data"]["index"])

    def test_parser_attributes_failure_and_dependency_skips(self) -> None:
        with TemporaryDirectory() as directory:
            root_path = Path(directory)
            store = ConfigStore(root_path / "config.json", root_path / "templates")
            optional = Step(
                name="optional",
                kind="find_and_tap",
                params={"templates": [{"file": "missing.png", "threshold": 0.8}]},
                on_failure="continue",
                screen_resolution=(100, 60),
            )
            dependent = Step(
                name="dependent", kind="wait", depends_on=[optional.id]
            )
            preset = Preset(name="root", steps=[optional, dependent])
            store.save(AppConfig(presets=[preset], selected_preset_id=preset.id))
            manager = RuntimeManager(store, FakeDevice())

            manager.start(preset.id)
            self.wait_until_idle(manager)

            skipped_ids = {
                event["data"]["step_id"]
                for event in manager.events()
                if event["type"] == "step" and event["data"]["state"] == "skipped"
            }
            self.assertEqual({optional.id, dependent.id}, skipped_ids)

    def test_mutation_serializes_read_modify_write(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = ConfigStore(root / "config.json", root / "templates")
            store.load()
            manager = RuntimeManager(store, FakeDevice())
            def append(index):
                with manager.mutation():
                    config = store.load()
                    config.presets.append(Preset(name=str(index)))
                    store.save(config)
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(append, range(20)))
            self.assertEqual(21, len(store.load().presets))

    def test_start_waits_for_mutation_without_blocking_status(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = ConfigStore(root / "config.json", root / "templates")
            preset = store.load().presets[0]
            manager = RuntimeManager(store, FakeDevice())
            entered, release, attempting = Event(), Event(), Event()
            def mutate():
                with manager.mutation():
                    entered.set()
                    release.wait(2)
                    config = store.load()
                    config.presets[0].name = "committed"
                    store.save(config)
            def start():
                attempting.set()
                return manager.start(preset.id)
            with ThreadPoolExecutor(max_workers=2) as pool:
                mutation = pool.submit(mutate)
                try:
                    self.assertTrue(entered.wait(1))
                    starting = pool.submit(start)
                    self.assertTrue(attempting.wait(1))
                    self.assertFalse(starting.done())
                    self.assertEqual("idle", manager.status()["state"])
                    async def subscribe():
                        _, _, subscriber = await manager.subscribe()
                        manager.unsubscribe(subscriber)
                    asyncio.run(subscribe())
                finally:
                    release.set()
                mutation.result(timeout=2)
                starting.result(timeout=2)
            self.wait_until_idle(manager)
            self.assertEqual("committed", store.load().presets[0].name)

    def test_subscriber_overflow_is_bounded_and_disconnects(self) -> None:
        async def check():
            with TemporaryDirectory() as directory:
                root = Path(directory)
                manager = RuntimeManager(ConfigStore(root / "config.json", root / "templates"),
                                         FakeDevice(), subscriber_limit=2)
                _, queue, subscriber = await manager.subscribe()
                for index in range(100):
                    manager.publish_device({"index": index})
                self.assertLessEqual(len(subscriber.pending), 2)
                await asyncio.sleep(0)
                self.assertTrue(subscriber.closed.is_set())
                self.assertLessEqual(queue.qsize(), 2)
                self.assertEqual([], manager._subscribers)
                _, queue, subscriber = await manager.subscribe()
                manager.publish_device({"index": 1})
                await asyncio.sleep(0)
                manager.publish_device({"index": 2})
                await asyncio.sleep(0)
                manager.publish_device({"index": 3})
                await asyncio.sleep(0)
                self.assertTrue(subscriber.closed.is_set())
        asyncio.run(check())

    def test_event_fanout_shares_owned_envelopes_and_copies_public_snapshots(self):
        async def check():
            with TemporaryDirectory() as directory:
                root = Path(directory)
                manager = RuntimeManager(ConfigStore(root / "config.json", root / "templates"),
                                         FakeDevice())
                _, first_queue, first = await manager.subscribe()
                _, second_queue, second = await manager.subscribe()
                source = {"nested": {"value": 1}}
                manager.publish_device(source)
                published = manager._events[-1]
                # Live delivery is a read-only consumer contract; fanout shares
                # this owned envelope instead of allocating it for every queue.
                self.assertIs(first.pending[0], published)
                self.assertIs(second.pending[0], published)
                source["nested"]["value"] = 99
                self.assertEqual(1, published["data"]["nested"]["value"])
                await asyncio.sleep(0)
                self.assertIs(first_queue.get_nowait(), published)
                self.assertIs(second_queue.get_nowait(), published)
                history = manager.events()
                history[-1]["data"]["nested"]["value"] = 88
                backlog, _, third = await manager.subscribe()
                backlog[0]["data"]["nested"]["value"] = 77
                self.assertEqual(1, manager.events()[-1]["data"]["nested"]["value"])
                for subscriber in (first, second, third):
                    manager.unsubscribe(subscriber)
        asyncio.run(check())

    def test_shared_events_do_not_alias_mutable_node_and_frame_state(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manager = RuntimeManager(ConfigStore(root / "config.json", root / "templates"),
                                     FakeDevice())
            manager._frames["frame"] = {"frame_id": "frame", "step_index": 1}
            manager._publish({"type": "status", "data": {}})
            manager._publish({"type": "step", "data": {
                "step_id": "node", "state": "running", "details": {"value": 1}}})
            manager._frames["frame"]["step_index"] = 2
            manager._node_states["node"]["state"] = "idle"
            manager._node_states["node"]["details"]["value"] = 2
            snapshot = manager.status()
            snapshot["frames"][0]["step_index"] = 3
            snapshot["node_states"]["node"]["details"]["value"] = 3
            status_event, step_event = manager.events()
            self.assertEqual(1, status_event["data"]["frames"][0]["step_index"])
            self.assertEqual("running", step_event["data"]["state"])
            self.assertEqual(1, step_event["data"]["details"]["value"])
            self.assertEqual(2, manager.status()["frames"][0]["step_index"])
            self.assertEqual(2, manager.status()["node_states"]["node"]["details"]["value"])

    def test_parser_unwinds_failed_and_empty_child_frames(self) -> None:
        child_step = Step(name="bad", kind="wait")
        child = Preset(name="child", steps=[child_step])
        call = Step(name="call", kind="run_preset", params={"preset_id": child.id},
                    on_failure="continue")
        next_step = Step(name="next", kind="wait")
        root = Preset(name="root", steps=[call, next_step])
        for terminal in ["  中止：bad", "预设没有启用的步骤"]:
            parser = _LogParser({root.id: root, child.id: child}, root)
            parser.process("开始执行预设：root（2 个步骤，循环 1）")
            parser.process("[1/2] call")
            parser.process("开始执行预设：child（1 个步骤，循环 1）")
            if terminal.startswith("  中止"):
                parser.process("[1/1] bad")
            parser.process(terminal)
            step_id, _ = parser.process("  跳过：child failure")
            self.assertEqual(call.id, step_id)
            step_id, events = parser.process("[2/2] next")
            self.assertEqual(next_step.id, step_id)
            self.assertEqual(root.id, events[-1]["data"]["preset_id"])


class StructuredRuntimeTests(unittest.TestCase):
    wait_until_idle = staticmethod(RuntimeManagerTests.wait_until_idle)
    def test_nested_same_names_reconnect_snapshot_and_parent_restore(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            store = ConfigStore(path / "config.json", path / "templates")
            entered, release = Event(), Event()
            registry = StepRegistry()
            child_step = Step(name="same", kind="wait")
            child = Preset(name="same", steps=[child_step], loop_count=2)
            parent = Step(name="same", kind="tap", params={"x": 0, "y": 0})
            root = Preset(name="same", steps=[parent])
            def hold(_step, context):
                # Log content cannot alter structured state.
                context.log("预设执行完成")
                entered.set()
                release.wait(2)
                return StepResult(True)
            def nested(_step, context):
                from dataclasses import replace
                report = context.engine.run(child, replace(context))
                return StepResult(report.status == "completed")
            registry.register(StepDefinition("wait", "Hold", (), hold))
            registry.register(StepDefinition("tap", "Child", (), nested))
            store.save(AppConfig(presets=[root], selected_preset_id=root.id))
            manager = RuntimeManager(store, FakeDevice(), registry=registry, event_limit=3)
            manager.start(root.id)
            try:
                self.assertTrue(entered.wait(1))
                snapshot = manager.status()
                self.assertEqual(child.id, snapshot["preset_id"])
                self.assertEqual(1, snapshot["root_cycle"])
                self.assertEqual("running", snapshot["node_states"][parent.id]["state"])
                self.assertEqual("running", snapshot["node_states"][child_step.id]["state"])
                self.assertEqual(2, len(snapshot["frames"]))
                async def reconnect():
                    backlog, _, subscriber = await manager.subscribe()
                    manager.unsubscribe(subscriber)
                    self.assertEqual("status", backlog[-1]["type"])
                    self.assertEqual(snapshot, backlog[-1]["data"])
                    self.assertTrue(all(e["type"] in {"log", "device"} for e in backlog[:-1]))
                asyncio.run(reconnect())
            finally:
                release.set()
            self.wait_until_idle(manager)
            status = manager.status()
            self.assertEqual([], status["frames"])
            self.assertEqual("done", status["node_states"][parent.id]["state"])
            self.assertEqual("done", status["node_states"][child_step.id]["state"])
            self.assertEqual(1, status["root_cycle"])
            events = manager.events()
            self.assertEqual(sorted(e["seq"] for e in events), [e["seq"] for e in events])
            self.assertEqual(1, len({e["run_id"] for e in events}))
            self.assertTrue(all("node_states" not in e["data"] for e in events if e["type"] == "status"))

    def test_stop_and_fake_exception_clear_frames_and_running_nodes(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            store = ConfigStore(path / "config.json", path / "templates")
            entered = Event()
            registry = StepRegistry()
            def hold(_step, context):
                entered.set()
                context.stop_event.wait(2)
                return StepResult(True)
            registry.register(StepDefinition("wait", "Hold", (), hold))
            step = Step(name="event", kind="wait")
            preset = Preset(name="events", steps=[step])
            store.save(AppConfig(presets=[preset], selected_preset_id=preset.id))
            manager = RuntimeManager(store, FakeDevice(), registry=registry)
            manager.start(preset.id)
            self.assertTrue(entered.wait(1))
            manager.stop()
            self.wait_until_idle(manager)
            status = manager.status()
            self.assertEqual("stopped", status["last_status"])
            self.assertEqual([], status["frames"])
            self.assertEqual("idle", status["node_states"][step.id]["state"])

    def test_legacy_engine_parser_still_updates_snapshot(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            store = ConfigStore(path / "config.json", path / "templates")
            step = Step(name="old", kind="wait")
            preset = Preset(name="root", steps=[step])
            store.save(AppConfig(presets=[preset], selected_preset_id=preset.id))
            class Legacy:
                def run(self, _preset, context):
                    context.log("开始执行预设：root（1 个步骤，循环 1）")
                    context.log("[1/1] old")
                    context.log("  完成：ok")
                    context.log("预设执行完成")
                    return ExecutionReport("completed", "done")
            manager = RuntimeManager(store, FakeDevice(), engine_factory=lambda _: Legacy())
            manager.start(preset.id)
            self.wait_until_idle(manager)
            self.assertEqual("done", manager.status()["node_states"][step.id]["state"])


class StartStepRuntimeTests(unittest.TestCase):
    wait_until_idle = staticmethod(RuntimeManagerTests.wait_until_idle)

    @staticmethod
    def _manager(directory: str, preset: Preset, calls: list[str]) -> RuntimeManager:
        store = ConfigStore(Path(directory) / "config.json", Path(directory) / "templates")
        store.save(AppConfig(presets=[preset], selected_preset_id=preset.id))
        registry = StepRegistry()

        def run(step: Step, _context: RuntimeContext) -> StepResult:
            calls.append(step.name)
            return StepResult(True, "ok")

        registry.register(StepDefinition("wait", "Pass", (), run))
        return RuntimeManager(store, FakeDevice(), registry=registry)

    def test_start_forwards_start_step_and_runs_only_the_suffix(self) -> None:
        calls: list[str] = []
        first = Step(name="first", kind="wait")
        second = Step(name="second", kind="wait")
        preset = Preset(name="start", steps=[first, second])
        with TemporaryDirectory() as directory:
            manager = self._manager(directory, preset, calls)
            status = manager.start(preset.id, second.id)
            self.assertEqual("running", status["state"])
            self.wait_until_idle(manager)

        self.assertEqual(["second"], calls)
        self.assertEqual("completed", manager.status()["last_status"])
        running = {
            event["data"]["step_id"]
            for event in manager.events()
            if event["type"] == "step" and event["data"]["state"] == "running"
        }
        self.assertEqual({second.id}, running)

    def test_start_rejects_unknown_and_disabled_start_steps(self) -> None:
        calls: list[str] = []
        disabled = Step(name="disabled", kind="wait", enabled=False)
        available = Step(name="available", kind="wait")
        preset = Preset(name="invalid", steps=[disabled, available])
        with TemporaryDirectory() as directory:
            manager = self._manager(directory, preset, calls)
            for start_id in ("missing", disabled.id):
                with self.subTest(start_id=start_id):
                    with self.assertRaises(ValueError):
                        manager.start(preset.id, start_id)
                    self.assertEqual("idle", manager.status()["state"])
        self.assertEqual([], calls)

    def test_start_without_start_step_keeps_full_run(self) -> None:
        calls: list[str] = []
        first = Step(name="first", kind="wait")
        second = Step(name="second", kind="wait")
        preset = Preset(name="full", steps=[first, second])
        with TemporaryDirectory() as directory:
            manager = self._manager(directory, preset, calls)
            manager.start(preset.id)
            self.wait_until_idle(manager)

        self.assertEqual(["first", "second"], calls)
        self.assertEqual("completed", manager.status()["last_status"])


if __name__ == "__main__":
    unittest.main()
