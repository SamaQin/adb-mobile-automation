from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

import cv2
import numpy as np

from model_automation.models import Preset, Step
from model_automation.preset_archive import (
    PresetArchiveError,
    export_preset,
    import_preset,
    scale_step,
)


def write_image(path: Path, width: int = 10, height: int = 20, value: int = 80) -> None:
    image = np.full((height, width, 3), value, dtype=np.uint8)
    success = cv2.imwrite(str(path), image)
    if not success:
        raise OSError(f"无法创建测试图片 {path}")


class PresetArchiveTests(unittest.TestCase):
    def test_public_scale_step_returns_recursive_copy(self) -> None:
        branch = Step(
            name="分支点击",
            kind="tap",
            params={"x": 10, "y": 20},
            screen_resolution=(100, 200),
        )
        source = Step(
            name="识别",
            kind="find_and_tap",
            params={
                "templates": [{"file": "button.png", "threshold": 0.8}],
                "branches": {"0": [branch.to_dict()]},
            },
            screen_resolution=(100, 200),
        )

        scaled = scale_step(source, (200, 400))

        scaled_branch = scaled.params["branches"]["0"][0]
        self.assertEqual({"x": 20, "y": 40}, scaled_branch["params"])
        self.assertEqual({"x": 10, "y": 20}, branch.params)
        self.assertEqual((100, 200), source.screen_resolution)

        with self.assertRaisesRegex(PresetArchiveError, "必须大于 0"):
            scale_step(source, (0, 400))

    def test_export_import_scales_coordinates_templates_and_dependencies(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_templates = root / "source_templates"
            target_templates = root / "target_templates"
            source_templates.mkdir()
            write_image(source_templates / "button.png")
            first = Step(
                name="点击",
                kind="tap",
                params={"x": 25, "y": 50, "wait_after": 1.5},
                screen_resolution=(100, 200),
            )
            second = Step(
                name="识别",
                kind="find_and_tap",
                params={
                    "templates": [{"file": "button.png", "threshold": 0.9}],
                    "attempts": 2,
                    "interval": 1.0,
                    "swipe_between": True,
                    "x1": 10,
                    "y1": 180,
                    "x2": 90,
                    "y2": 20,
                    "duration": 300,
                    "click_x": 25,
                    "click_y": 75,
                    "offset_x": -5,
                    "offset_y": 8,
                    "wait_after": 0.0,
                },
                depends_on=[first.id],
                screen_resolution=(100, 200),
            )
            preset = Preset(name="测试预设", steps=[first, second], loop_count=3)
            archive = root / "preset.adb-preset.zip"

            export_preset(preset, source_templates, archive)
            imported = import_preset(archive, target_templates, (200, 400))

            self.assertNotEqual(preset.id, imported.id)
            self.assertEqual("测试预设", imported.name)
            self.assertEqual(3, imported.loop_count)
            self.assertNotEqual(first.id, imported.steps[0].id)
            self.assertEqual([imported.steps[0].id], imported.steps[1].depends_on)
            self.assertEqual((200, 400), imported.steps[0].screen_resolution)
            self.assertEqual({"x": 50, "y": 100, "wait_after": 1.5}, imported.steps[0].params)
            params = imported.steps[1].params
            self.assertEqual((20, 360, 180, 40), (params["x1"], params["y1"], params["x2"], params["y2"]))
            self.assertEqual((50, 150), (params["click_x"], params["click_y"]))
            self.assertEqual((-10, 16), (params["offset_x"], params["offset_y"]))
            self.assertEqual(300, params["duration"])
            self.assertEqual(0.9, params["templates"][0]["threshold"])
            self.assertEqual(
                {"width": 200, "height": 400},
                params["templates"][0]["screen_resolution"],
            )
            imported_image = cv2.imread(
                str(target_templates / params["templates"][0]["file"])
            )
            self.assertIsNotNone(imported_image)
            self.assertEqual((40, 20), imported_image.shape[:2])

    def test_import_does_not_overwrite_different_existing_template(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_templates = root / "source_templates"
            target_templates = root / "target_templates"
            source_templates.mkdir()
            target_templates.mkdir()
            write_image(source_templates / "button.png", value=40)
            write_image(target_templates / "button.png", value=200)
            step = Step(
                name="识别",
                kind="find_and_tap",
                params={"templates": [{"file": "button.png", "threshold": 0.8}]},
                screen_resolution=(100, 200),
            )
            archive = root / "preset.zip"
            export_preset(Preset(name="预设", steps=[step]), source_templates, archive)

            imported = import_preset(archive, target_templates, (100, 200))

            imported_name = imported.steps[0].params["templates"][0]["file"]
            self.assertEqual("button_imported.png", imported_name)
            existing = cv2.imread(str(target_templates / "button.png"))
            imported_image = cv2.imread(str(target_templates / imported_name))
            self.assertEqual(200, int(existing[0, 0, 0]))
            self.assertEqual(40, int(imported_image[0, 0, 0]))

    def test_export_reports_missing_template(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            templates = root / "templates"
            templates.mkdir()
            preset = Preset(
                name="预设",
                steps=[
                    Step(
                        name="识别",
                        kind="find_and_tap",
                        params={"templates": [{"file": "missing.png"}]},
                        screen_resolution=(100, 200),
                    )
                ],
            )

            with self.assertRaisesRegex(PresetArchiveError, "missing.png"):
                export_preset(preset, templates, root / "preset.zip")

    def test_export_rejects_coordinate_step_without_resolution(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "preset.zip"
            preset = Preset(
                name="旧预设",
                steps=[Step(name="点击", kind="tap", params={"x": 10, "y": 20})],
            )
            with self.assertRaisesRegex(PresetArchiveError, "没有记录屏幕分辨率"):
                export_preset(preset, root, archive)

    def test_import_rejects_coordinate_step_without_resolution(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "preset.zip"
            preset = Preset(
                name="旧预设",
                steps=[Step(name="点击", kind="tap", params={"x": 10, "y": 20})],
            )
            manifest = {
                "archive_version": 1,
                "preset": preset.to_dict(),
                "assets": [],
            }
            with ZipFile(archive, "w", compression=ZIP_DEFLATED) as package:
                package.writestr("manifest.json", json.dumps(manifest))

            with self.assertRaisesRegex(PresetArchiveError, "没有记录屏幕分辨率"):
                import_preset(archive, root / "templates", (200, 400))

    def test_import_scales_coordinate_defaults(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "preset.zip"
            preset = Preset(
                name="默认坐标",
                steps=[
                    Step(
                        name="滑动",
                        kind="swipe",
                        params={},
                        screen_resolution=(1080, 2400),
                    )
                ],
            )
            export_preset(preset, root, archive)

            imported = import_preset(archive, root / "templates", (2160, 4800))

            self.assertEqual(
                {"x1": 1080, "y1": 3600, "x2": 1080, "y2": 1600},
                {
                    key: imported.steps[0].params[key]
                    for key in ("x1", "y1", "x2", "y2")
                },
            )

    def test_malformed_step_is_reported_as_archive_error(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "preset.zip"
            manifest = {
                "archive_version": 1,
                "preset": {"name": "损坏", "steps": [None]},
                "assets": [],
            }
            with ZipFile(archive, "w", compression=ZIP_DEFLATED) as package:
                package.writestr("manifest.json", json.dumps(manifest))

            with self.assertRaises(PresetArchiveError):
                import_preset(archive, root / "templates", (100, 200))

    def test_export_import_scales_and_renames_branch_steps(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_templates = root / "source_templates"
            target_templates = root / "target_templates"
            source_templates.mkdir()
            write_image(source_templates / "button.png")
            write_image(source_templates / "branch_button.png", value=120)
            branch_step = Step(
                name="分支识别",
                kind="find_and_tap",
                params={
                    "templates": [{"file": "branch_button.png", "threshold": 0.8}],
                    "attempts": 1,
                    "interval": 1.0,
                    "swipe_between": False,
                    "x1": 10,
                    "y1": 180,
                    "x2": 90,
                    "y2": 20,
                    "duration": 300,
                    "click_x": 30,
                    "click_y": 60,
                    "wait_after": 0.0,
                },
                screen_resolution=(100, 200),
            )
            step = Step(
                name="识别",
                kind="find_and_tap",
                params={
                    "templates": [
                        {"file": "button.png", "threshold": 0.9},
                        {"file": "branch_button.png", "threshold": 0.8},
                    ],
                    "attempts": 2,
                    "interval": 1.0,
                    "swipe_between": False,
                    "x1": 10,
                    "y1": 180,
                    "x2": 90,
                    "y2": 20,
                    "duration": 300,
                    "click_x": 25,
                    "click_y": 75,
                    "wait_after": 0.0,
                    "branches": {"1": [branch_step.to_dict()]},
                },
                screen_resolution=(100, 200),
            )
            preset = Preset(name="分支预设", steps=[step])
            archive = root / "preset.adb-preset.zip"

            export_preset(preset, source_templates, archive)
            imported = import_preset(archive, target_templates, (200, 400))

            branch = imported.steps[0].params["branches"]["1"][0]
            self.assertEqual(
                {"width": 200, "height": 400}, branch["screen_resolution"]
            )
            self.assertEqual((20, 360, 180, 40), (
                branch["params"]["x1"],
                branch["params"]["y1"],
                branch["params"]["x2"],
                branch["params"]["y2"],
            ))
            self.assertEqual((60, 120), (
                branch["params"]["click_x"],
                branch["params"]["click_y"],
            ))
            self.assertEqual(0.8, branch["params"]["templates"][0]["threshold"])
            imported_image = cv2.imread(
                str(target_templates / branch["params"]["templates"][0]["file"])
            )
            self.assertIsNotNone(imported_image)
            self.assertEqual((40, 20), imported_image.shape[:2])

    def test_export_reports_missing_branch_template(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            templates = root / "templates"
            templates.mkdir()
            write_image(templates / "button.png")
            branch_step = Step(
                name="分支识别",
                kind="find_and_tap",
                params={"templates": [{"file": "missing.png"}]},
                screen_resolution=(100, 200),
            )
            step = Step(
                name="识别",
                kind="find_and_tap",
                params={
                    "templates": [{"file": "button.png", "threshold": 0.9}],
                    "branches": {"0": [branch_step.to_dict()]},
                },
                screen_resolution=(100, 200),
            )

            with self.assertRaisesRegex(PresetArchiveError, "missing.png"):
                export_preset(
                    Preset(name="预设", steps=[step]), templates, root / "preset.zip"
                )

    def test_import_remaps_ids_and_dependencies_in_nested_branches(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            templates = root / "templates"
            imported_templates = root / "imported_templates"
            templates.mkdir()
            write_image(templates / "button.png")
            nested_first = Step(name="嵌套一", kind="wait")
            nested_second = Step(
                name="嵌套二", kind="wait", depends_on=[nested_first.id]
            )
            branch_first = Step(name="分支一", kind="wait")
            branch_second = Step(
                name="分支识别",
                kind="find_and_tap",
                params={
                    "templates": [{"file": "button.png", "threshold": 0.8}],
                    "branches": {
                        "0": [nested_first.to_dict(), nested_second.to_dict()]
                    },
                },
                depends_on=[branch_first.id],
                screen_resolution=(100, 200),
            )
            top = Step(
                name="顶层识别",
                kind="find_and_tap",
                params={
                    "templates": [{"file": "button.png", "threshold": 0.8}],
                    "branches": {
                        "0": [branch_first.to_dict(), branch_second.to_dict()]
                    },
                },
                screen_resolution=(100, 200),
            )
            preset = Preset(name="递归", steps=[top])
            archive = root / "nested.zip"

            export_preset(preset, templates, archive)
            imported = import_preset(archive, imported_templates, (100, 200))

            branch = imported.steps[0].params["branches"]["0"]
            nested = branch[1]["params"]["branches"]["0"]
            old_ids = {
                top.id,
                branch_first.id,
                branch_second.id,
                nested_first.id,
                nested_second.id,
            }
            new_ids = {
                imported.steps[0].id,
                branch[0]["id"],
                branch[1]["id"],
                nested[0]["id"],
                nested[1]["id"],
            }
            self.assertTrue(old_ids.isdisjoint(new_ids))
            self.assertEqual([branch[0]["id"]], branch[1]["depends_on"])
            self.assertEqual([nested[0]["id"]], nested[1]["depends_on"])

    def test_export_rejects_branch_step_without_resolution(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            templates = root / "templates"
            templates.mkdir()
            branch_step = Step(
                name="分支点击",
                kind="tap",
                params={"x": 10, "y": 20},
            )
            step = Step(
                name="识别",
                kind="find_and_tap",
                params={
                    "templates": [],
                    "branches": {"0": [branch_step.to_dict()]},
                },
                screen_resolution=(100, 200),
            )
            preset = Preset(name="预设", steps=[step])

            with self.assertRaisesRegex(PresetArchiveError, "没有记录屏幕分辨率"):
                export_preset(preset, templates, root / "preset.zip")

    def test_import_rejects_archive_without_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "bad.zip"
            with ZipFile(archive, "w", compression=ZIP_DEFLATED) as package:
                package.writestr("other.json", "{}")

            with self.assertRaisesRegex(PresetArchiveError, "manifest.json"):
                import_preset(archive, root / "templates", (100, 200))


if __name__ == "__main__":
    unittest.main()
