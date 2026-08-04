import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from model_automation.config import ConfigError, ConfigStore


class ConfigStoreTests(unittest.TestCase):
    def test_missing_config_creates_default_preset(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = ConfigStore(root / "config.json", root / "templates")

            config = store.load()

            self.assertTrue((root / "config.json").exists())
            self.assertTrue((root / "templates").is_dir())
            self.assertEqual("默认预设", config.selected_preset().name)
            self.assertEqual([], config.selected_preset().steps)
            self.assertEqual(1, config.selected_preset().loop_count)

    def test_legacy_coordinates_are_migrated(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.json"
            path.write_text(
                json.dumps({"support_pos": [123, 456], "start_pos": [789, 1011]}),
                encoding="utf-8",
            )
            store = ConfigStore(path, root / "templates")

            config = store.load()
            steps = config.selected_preset().steps

            self.assertEqual({"x": 123, "y": 456, "wait_after": 1.0}, steps[2].params)
            self.assertEqual({"x": 789, "y": 1011, "wait_after": 0.0}, steps[4].params)
            self.assertEqual(1, config.selected_preset().loop_count)
            self.assertEqual(2, json.loads(path.read_text(encoding="utf-8"))["version"])

    def test_non_object_config_reports_config_error(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.json"
            path.write_text("[]", encoding="utf-8")

            with self.assertRaises(ConfigError):
                ConfigStore(path, root / "templates").load()

    def test_newer_schema_is_not_rewritten(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.json"
            content = '{"version": 3, "presets": []}'
            path.write_text(content, encoding="utf-8")

            with self.assertRaises(ConfigError):
                ConfigStore(path, root / "templates").load()

            self.assertEqual(content, path.read_text(encoding="utf-8"))

    def test_depends_on_roundtrips_through_config(self) -> None:
        from model_automation.models import Step

        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.json"
            store = ConfigStore(path, root / "templates")
            config = store.load()
            first = Step(name="前置", kind="wait", params={"seconds": 0})
            config.selected_preset().steps = [
                first,
                Step(name="关联", kind="wait", params={"seconds": 0}, depends_on=[first.id]),
            ]
            store.save(config)

            loaded = ConfigStore(path, root / "templates").load()

            steps = loaded.selected_preset().steps
            self.assertEqual([first.id], steps[1].depends_on)

    def test_step_screen_resolution_roundtrips_through_config(self) -> None:
        from model_automation.models import Step

        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.json"
            store = ConfigStore(path, root / "templates")
            config = store.load()
            config.selected_preset().steps = [
                Step(
                    name="点击",
                    kind="tap",
                    params={"x": 100, "y": 200},
                    screen_resolution=(1080, 2400),
                )
            ]

            store.save(config)
            loaded = store.load()

            self.assertEqual((1080, 2400), loaded.selected_preset().steps[0].screen_resolution)


    def test_branch_and_preset_params_roundtrip_through_config(self) -> None:
        from model_automation.models import Preset, Step

        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.json"
            store = ConfigStore(path, root / "templates")
            config = store.load()
            sub = Preset(name="子预设")
            branch = Step(
                name="分支等待",
                kind="wait",
                params={"seconds": 2},
            )
            config.presets = [
                Preset(
                    name="父预设",
                    steps=[
                        Step(
                            name="识别",
                            kind="find_and_tap",
                            params={
                                "templates": [
                                    {"file": "a.png", "threshold": 0.8}
                                ],
                                "require_all": True,
                                "branches": {"0": [branch.to_dict()]},
                            },
                        ),
                        Step(
                            name="执行子预设",
                            kind="run_preset",
                            params={
                                "preset_id": sub.id,
                                "preset_name": sub.name,
                            },
                        ),
                    ],
                ),
                sub,
            ]
            config.selected_preset_id = config.presets[0].id
            store.save(config)

            loaded = ConfigStore(path, root / "templates").load()
            recognition, run_preset = loaded.presets[0].steps

        self.assertTrue(recognition.params["require_all"])
        self.assertEqual(
            [branch.to_dict()],
            recognition.params["branches"]["0"],
        )
        self.assertEqual(sub.id, run_preset.params["preset_id"])
        self.assertEqual("子预设", run_preset.params["preset_name"])


    def test_acceleration_roundtrips_through_config(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.json"
            store = ConfigStore(path, root / "templates")
            config = store.load()
            self.assertEqual("cpu", config.acceleration)
            config.acceleration = "gpu"
            store.save(config)

            loaded = ConfigStore(path, root / "templates").load()

            self.assertEqual("gpu", loaded.acceleration)
            self.assertEqual(
                "gpu",
                json.loads(path.read_text(encoding="utf-8"))["acceleration"],
            )

    def test_unknown_acceleration_value_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "config.json"
            store = ConfigStore(path, root / "templates")
            config = store.load()
            config.acceleration = "quantum"
            store.save(config)

            with self.assertRaises(ConfigError):
                ConfigStore(path, root / "templates").load()


if __name__ == "__main__":
    unittest.main()
