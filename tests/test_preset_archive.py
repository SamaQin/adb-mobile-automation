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


class RoiScalingTests(unittest.TestCase):
    def recognition(self, bounds, resolution=(100, 200)):
        x, y, width, height = bounds
        return Step(name="roi", kind="find_and_tap", screen_resolution=resolution, params={
            "templates": [{"file": "target.png"}], "roi_enabled": True,
            "search_x": x, "search_y": y, "search_width": width, "search_height": height})

    def bounds(self, step):
        return tuple(step.params[key] for key in
                     ("search_x", "search_y", "search_width", "search_height"))

    def test_full_screen_roi_keeps_exclusive_right_bottom_edges(self):
        source = self.recognition((0, 0, 100, 200))
        self.assertEqual((0, 0, 200, 600), self.bounds(scale_step(source, (200, 600))))
        self.assertEqual((0, 0, 100, 200), self.bounds(source))

    def test_roi_scales_boundaries_together_for_rounding_and_nested_branches(self):
        source = self.recognition((1, 1, 1, 1), (7, 7))
        nested = self.recognition((3, 3, 4, 4), (7, 7))
        source.params["branches"] = {"0": [nested.to_dict()]}
        scaled = scale_step(source, (10, 10))
        self.assertEqual((1, 1, 2, 2), self.bounds(scaled))
        branch = Step.from_dict(scaled.params["branches"]["0"][0])
        self.assertEqual((4, 4, 6, 6), self.bounds(branch))

    def test_invalid_and_empty_after_scaling_roi_are_rejected(self):
        for bounds in ((-1, 0, 10, 10), (0, 0, 0, 10), (90, 0, 11, 10)):
            with self.subTest(bounds=bounds), self.assertRaisesRegex(PresetArchiveError, "ROI"):
                scale_step(self.recognition(bounds), (200, 400))
        with self.assertRaisesRegex(PresetArchiveError, "缩放后为空"):
            scale_step(self.recognition((0, 0, 1, 1)), (1, 1))

    def test_archive_import_scales_roi_and_template_together(self):
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            write_image(folder / "target.png", width=10, height=10)
            step = self.recognition((80, 170, 20, 30))
            archive = folder / "preset.zip"
            export_preset(Preset(name="roi", steps=[step]), folder, archive)
            imported = import_preset(archive, folder / "imported", (200, 600))
            self.assertEqual((160, 510, 40, 90), self.bounds(imported.steps[0]))
            filename = imported.steps[0].params["templates"][0]["file"]
            self.assertEqual((30, 20), cv2.imread(str(folder / "imported" / filename)).shape[:2])


class RecordedActionScalingTests(unittest.TestCase):
    def test_scales_tap_and_swipe_actions_without_mutating_source(self) -> None:
        source = Step(
            name="录制",
            kind="recorded_actions",
            screen_resolution=(100, 200),
            params={"actions": [
                {"type": "tap", "x": 10, "y": 20, "at": 0},
                {"type": "swipe", "x1": 20, "y1": 40, "x2": 50, "y2": 100,
                 "duration": 300, "at": 500},
            ]},
        )

        scaled = scale_step(source, (200, 400))

        self.assertEqual([
            {"type": "tap", "x": 20, "y": 40, "at": 0},
            {"type": "swipe", "x1": 40, "y1": 80, "x2": 100, "y2": 200,
             "duration": 300, "at": 500},
        ], scaled.params["actions"])
        self.assertEqual(10, source.params["actions"][0]["x"])
        self.assertEqual((100, 200), source.screen_resolution)

    def test_scales_recorded_actions_inside_branches(self) -> None:
        recorded = Step(
            name="分支录制",
            kind="recorded_actions",
            screen_resolution=(100, 200),
            params={"actions": [{"type": "tap", "x": 50, "y": 100, "at": 0}]},
        )
        source = Step(
            name="识别",
            kind="find_and_tap",
            screen_resolution=(100, 200),
            params={
                "templates": [{"file": "target.png"}],
                "branches": {"0": [recorded.to_dict()]},
            },
        )

        scaled = scale_step(source, (200, 400))
        branch = Step.from_dict(scaled.params["branches"]["0"][0])

        self.assertEqual([{"type": "tap", "x": 100, "y": 200, "at": 0}],
                         branch.params["actions"])
        self.assertEqual((200, 400), branch.screen_resolution)

    def test_rejects_actions_without_source_resolution(self) -> None:
        source = Step(
            name="录制",
            kind="recorded_actions",
            params={"actions": [{"type": "tap", "x": 10, "y": 20, "at": 0}]},
        )

        with self.assertRaisesRegex(PresetArchiveError, "没有记录屏幕分辨率"):
            scale_step(source, (200, 400))

    def test_empty_actions_do_not_require_resolution(self) -> None:
        source = Step(name="空录制", kind="recorded_actions", params={"actions": []})

        scaled = scale_step(source, (200, 400))

        self.assertEqual([], scaled.params["actions"])
        self.assertEqual((200, 400), scaled.screen_resolution)


if __name__ == "__main__":
    unittest.main()
