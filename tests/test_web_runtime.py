from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import time
import unittest

import numpy as np

from model_automation.config import ConfigStore
from model_automation.engine import ExecutionReport
from model_automation.models import AppConfig, Preset, Step
from web_server.runtime import RuntimeConflict, RuntimeManager


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


if __name__ == "__main__":
    unittest.main()
