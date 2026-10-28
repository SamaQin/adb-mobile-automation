from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from model_automation import vision

from model_automation.engine import RuntimeContext, StepEngine, StepResult
from model_automation.models import Preset, Step
from model_automation.registry import StepDefinition, StepRegistry
from model_automation.steps import (
    REGISTRY,
    run_find_and_multi_tap,
    run_find_and_tap,
    run_recorded_actions,
    run_run_preset,
    step_summary,
)
from model_automation.vision import save_image


class FakeDevice:
    def __init__(self, screen: np.ndarray) -> None:
        self.screen = screen
        self.taps: list[tuple[int, int]] = []
        self.swipes: list[tuple[int, int, int, int, int]] = []
        self.actions: list[tuple[str, tuple]] = []

    def screenshot(self) -> np.ndarray:
        return self.screen.copy()

    def tap(self, x: int, y: int) -> None:
        self.taps.append((x, y))
        self.actions.append(("tap", (x, y)))

    def swipe(
        self, x1: int, y1: int, x2: int, y2: int, duration: int
    ) -> None:
        self.swipes.append((x1, y1, x2, y2, duration))
        self.actions.append(("swipe", (x1, y1, x2, y2, duration)))


class FindAndTapTests(unittest.TestCase):
    def test_matching_template_taps_its_center_by_default(self) -> None:
        random = np.random.default_rng(7)
        screen = random.integers(0, 255, (80, 100, 3), dtype=np.uint8)
        template = screen[20:40, 30:55].copy()

        with TemporaryDirectory() as directory:
            template_dir = Path(directory)
            save_image(template_dir / "target.png", template)
            device = FakeDevice(screen)
            context = RuntimeContext(
                device=device,
                template_dir=template_dir,
                stop_event=Event(),
                log=lambda _message: None,
            )
            step = Step(
                name="find",
                kind="find_and_tap",
                params={
                    "templates": [{"file": "target.png", "threshold": 0.99}],
                    "attempts": 1,
                },
            )

            result = run_find_and_tap(step, context)

        self.assertTrue(result.success)
        self.assertEqual([(42, 30)], device.taps)

    def test_custom_click_toggle_taps_custom_coordinate(self) -> None:
        random = np.random.default_rng(7)
        screen = random.integers(0, 255, (80, 100, 3), dtype=np.uint8)
        template = screen[20:40, 30:55].copy()

        with TemporaryDirectory() as directory:
            template_dir = Path(directory)
            save_image(template_dir / "target.png", template)
            device = FakeDevice(screen)
            context = RuntimeContext(
                device=device,
                template_dir=template_dir,
                stop_event=Event(),
                log=lambda _message: None,
            )
            step = Step(
                name="find",
                kind="find_and_tap",
                params={
                    "templates": [{"file": "target.png", "threshold": 0.99}],
                    "attempts": 1,
                    "custom_click": True,
                    "click_x": 12,
                    "click_y": 13,
                },
            )

            result = run_find_and_tap(step, context)

        self.assertTrue(result.success)
        self.assertEqual([(12, 13)], device.taps)

    def test_offset_applies_to_template_center(self) -> None:
        random = np.random.default_rng(73)
        screen = random.integers(0, 255, (80, 100, 3), dtype=np.uint8)
        template = screen[20:40, 30:55].copy()

        with TemporaryDirectory() as directory:
            template_dir = Path(directory)
            save_image(template_dir / "target.png", template)
            device = FakeDevice(screen)
            context = RuntimeContext(
                device=device,
                template_dir=template_dir,
                stop_event=Event(),
                log=lambda _message: None,
            )
            step = Step(
                name="find",
                kind="find_and_tap",
                params={
                    "templates": [{"file": "target.png", "threshold": 0.99}],
                    "attempts": 1,
                    "offset_x": 5,
                    "offset_y": -4,
                },
            )

            result = run_find_and_tap(step, context)

        self.assertTrue(result.success)
        self.assertEqual([(47, 26)], device.taps)

    def test_offset_combines_with_custom_click(self) -> None:
        random = np.random.default_rng(74)
        screen = random.integers(0, 255, (80, 100, 3), dtype=np.uint8)
        template = screen[20:40, 30:55].copy()

        with TemporaryDirectory() as directory:
            template_dir = Path(directory)
            save_image(template_dir / "target.png", template)
            device = FakeDevice(screen)
            context = RuntimeContext(
                device=device,
                template_dir=template_dir,
                stop_event=Event(),
                log=lambda _message: None,
            )
            step = Step(
                name="find",
                kind="find_and_tap",
                params={
                    "templates": [{"file": "target.png", "threshold": 0.99}],
                    "attempts": 1,
                    "custom_click": True,
                    "click_x": 60,
                    "click_y": 36,
                    "offset_x": 3,
                    "offset_y": 2,
                },
            )

            result = run_find_and_tap(step, context)

        self.assertTrue(result.success)
        self.assertEqual([(63, 38)], device.taps)

    def test_multiple_targets_tap_top_row_from_left_to_right(self) -> None:
        random = np.random.default_rng(23)
        screen = random.integers(0, 255, (100, 120, 3), dtype=np.uint8)
        template = random.integers(0, 255, (12, 16, 3), dtype=np.uint8)
        screen[55:67, 5:21] = template
        screen[10:22, 70:86] = template
        screen[10:22, 25:41] = template

        with TemporaryDirectory() as directory:
            template_dir = Path(directory)
            save_image(template_dir / "target.png", template)
            device = FakeDevice(screen)
            context = RuntimeContext(
                device=device,
                template_dir=template_dir,
                stop_event=Event(),
                log=lambda _message: None,
            )
            step = Step(
                name="find",
                kind="find_and_tap",
                params={
                    "templates": [{"file": "target.png", "threshold": 0.99}],
                    "attempts": 1,
                    "custom_click": True,
                    "click_x": 14,
                    "click_y": 15,
                },
            )

            result = run_find_and_tap(step, context)

        self.assertTrue(result.success)
        self.assertEqual([(14, 15)], device.taps)

    def test_multiple_template_types_share_spatial_priority(self) -> None:
        random = np.random.default_rng(29)
        screen = random.integers(0, 255, (100, 120, 3), dtype=np.uint8)
        lower_template = random.integers(0, 255, (12, 16, 3), dtype=np.uint8)
        upper_template = random.integers(0, 255, (10, 14, 3), dtype=np.uint8)
        screen[60:72, 10:26] = lower_template
        screen[15:25, 80:94] = upper_template

        with TemporaryDirectory() as directory:
            template_dir = Path(directory)
            save_image(template_dir / "lower.png", lower_template)
            save_image(template_dir / "upper.png", upper_template)
            device = FakeDevice(screen)
            context = RuntimeContext(
                device=device,
                template_dir=template_dir,
                stop_event=Event(),
                log=lambda _message: None,
            )
            step = Step(
                name="find",
                kind="find_and_tap",
                params={
                    "templates": [
                        {"file": "lower.png", "threshold": 0.99},
                        {"file": "upper.png", "threshold": 0.99},
                    ],
                    "attempts": 1,
                    "custom_click": True,
                    "click_x": 16,
                    "click_y": 17,
                },
            )

            result = run_find_and_tap(step, context)

        self.assertTrue(result.success)
        self.assertEqual([(16, 17)], device.taps)

    def test_failed_attempt_swipes_before_retry(self) -> None:
        random = np.random.default_rng(11)
        screen = random.integers(0, 255, (80, 100, 3), dtype=np.uint8)
        template = random.integers(0, 255, (20, 25, 3), dtype=np.uint8)

        with TemporaryDirectory() as directory:
            template_dir = Path(directory)
            save_image(template_dir / "missing.png", template)
            device = FakeDevice(screen)
            context = RuntimeContext(
                device=device,
                template_dir=template_dir,
                stop_event=Event(),
                log=lambda _message: None,
            )
            step = Step(
                name="find",
                kind="find_and_tap",
                params={
                    "templates": [{"file": "missing.png", "threshold": 1.0}],
                    "attempts": 2,
                    "interval": 0,
                    "swipe_between": True,
                    "x1": 1,
                    "y1": 2,
                    "x2": 3,
                    "y2": 4,
                    "duration": 500,
                },
            )

            result = run_find_and_tap(step, context)

        self.assertFalse(result.success)
        self.assertEqual([(1, 2, 3, 4, 500)], device.swipes)
        self.assertEqual([], device.taps)

    def test_failed_attempt_taps_before_retry(self) -> None:
        random = np.random.default_rng(13)
        screen = random.integers(0, 255, (80, 100, 3), dtype=np.uint8)
        template = random.integers(0, 255, (20, 25, 3), dtype=np.uint8)

        with TemporaryDirectory() as directory:
            template_dir = Path(directory)
            save_image(template_dir / "missing.png", template)
            device = FakeDevice(screen)
            context = RuntimeContext(
                device=device,
                template_dir=template_dir,
                stop_event=Event(),
                log=lambda _message: None,
            )
            step = Step(
                name="find",
                kind="find_and_tap",
                params={
                    "templates": [{"file": "missing.png", "threshold": 1.0}],
                    "attempts": 2,
                    "interval": 0,
                    "tap_between": True,
                    "tap_between_x": 11,
                    "tap_between_y": 12,
                    "swipe_between": True,
                    "x1": 1,
                    "y1": 2,
                    "x2": 3,
                    "y2": 4,
                    "duration": 500,
                },
            )

            result = run_find_and_tap(step, context)

        self.assertFalse(result.success)
        self.assertEqual([(11, 12)], device.taps)
        self.assertEqual([(1, 2, 3, 4, 500)], device.swipes)

    def test_retry_tap_before_retry_swipe_order(self) -> None:
        random = np.random.default_rng(15)
        screen = random.integers(0, 255, (80, 100, 3), dtype=np.uint8)
        template = random.integers(0, 255, (20, 25, 3), dtype=np.uint8)

        with TemporaryDirectory() as directory:
            template_dir = Path(directory)
            save_image(template_dir / "missing.png", template)
            device = FakeDevice(screen)
            context = RuntimeContext(
                device=device,
                template_dir=template_dir,
                stop_event=Event(),
                log=lambda _message: None,
            )
            step = Step(
                name="find",
                kind="find_and_tap",
                params={
                    "templates": [{"file": "missing.png", "threshold": 1.0}],
                    "attempts": 2,
                    "interval": 0,
                    "tap_between": True,
                    "swipe_between": True,
                },
            )

            result = run_find_and_tap(step, context)

        self.assertFalse(result.success)
        self.assertEqual([(540, 1000)], device.taps)
        self.assertEqual([(540, 1800, 540, 800, 300)], device.swipes)
        self.assertEqual(["tap", "swipe"], [action for action, _ in device.actions])

    def test_multi_tap_uses_custom_coordinate_for_every_click(self) -> None:
        random = np.random.default_rng(17)
        screen = random.integers(0, 255, (100, 120, 3), dtype=np.uint8)
        template = screen[30:50, 40:70].copy()

        with TemporaryDirectory() as directory:
            template_dir = Path(directory)
            save_image(template_dir / "target.png", template)
            device = FakeDevice(screen)
            context = RuntimeContext(
                device=device,
                template_dir=template_dir,
                stop_event=Event(),
                log=lambda _message: None,
            )
            step = Step(
                name="multi",
                kind="find_and_tap",
                params={
                    "templates": [{"file": "target.png", "threshold": 0.99}],
                    "attempts": 1,
                    "custom_click": True,
                    "click_x": 60,
                    "click_y": 36,
                    "tap_mode": "multi",
                    "click_count": 3,
                    "click_interval": 0,
                },
            )

            result = run_find_and_tap(step, context)

        self.assertTrue(result.success)
        self.assertEqual([(60, 36), (60, 36), (60, 36)], device.taps)

    def test_custom_coordinate_outside_screen_fails_without_clicking(self) -> None:
        random = np.random.default_rng(19)
        screen = random.integers(0, 255, (80, 100, 3), dtype=np.uint8)
        template = screen[20:40, 30:55].copy()

        with TemporaryDirectory() as directory:
            template_dir = Path(directory)
            save_image(template_dir / "target.png", template)
            device = FakeDevice(screen)
            context = RuntimeContext(
                device=device,
                template_dir=template_dir,
                stop_event=Event(),
                log=lambda _message: None,
            )
            step = Step(
                name="custom coordinate",
                kind="find_and_tap",
                params={
                    "templates": [{"file": "target.png", "threshold": 0.99}],
                    "attempts": 1,
                    "custom_click": True,
                    "click_x": 1000,
                    "click_y": 30,
                },
            )

            result = run_find_and_tap(step, context)

        self.assertFalse(result.success)
        self.assertIn("超出屏幕", result.message)
        self.assertEqual([], device.taps)


def make_context(
    device: FakeDevice,
    template_dir: Path,
    engine: StepEngine | None = None,
    presets: dict[str, Preset] | None = None,
) -> RuntimeContext:
    return RuntimeContext(
        device=device,
        template_dir=template_dir,
        stop_event=Event(),
        log=lambda _message: None,
        engine=engine,
        presets=presets,
    )


class BranchTests(unittest.TestCase):
    def test_branch_steps_execute_and_request_restart(self) -> None:
        random = np.random.default_rng(31)
        screen = random.integers(0, 255, (80, 100, 3), dtype=np.uint8)
        template = screen[20:40, 30:55].copy()

        with TemporaryDirectory() as directory:
            template_dir = Path(directory)
            save_image(template_dir / "target.png", template)
            device = FakeDevice(screen)
            context = make_context(device, template_dir, engine=StepEngine(REGISTRY))
            branch = Step(name="等待", kind="wait", params={"seconds": 0})
            step = Step(
                name="find",
                kind="find_and_tap",
                params={
                    "templates": [{"file": "target.png", "threshold": 0.99}],
                    "attempts": 1,
                    "branches": {"0": [branch.to_dict()]},
                },
            )

            result = run_find_and_tap(step, context)

        self.assertTrue(result.success)
        self.assertTrue(result.restart)
        self.assertEqual([], device.taps)

    def test_matched_template_with_branch_skips_step_action(self) -> None:
        random = np.random.default_rng(33)
        screen = random.integers(0, 255, (80, 100, 3), dtype=np.uint8)
        first = screen[20:40, 30:55].copy()
        second = random.integers(0, 255, (12, 16, 3), dtype=np.uint8)
        screen[60:72, 10:26] = second

        with TemporaryDirectory() as directory:
            template_dir = Path(directory)
            save_image(template_dir / "first.png", first)
            save_image(template_dir / "second.png", second)
            device = FakeDevice(screen)
            context = make_context(device, template_dir, engine=StepEngine(REGISTRY))
            branch = Step(name="等待", kind="wait", params={"seconds": 0})
            step = Step(
                name="find",
                kind="find_and_multi_tap",
                params={
                    "templates": [
                        {"file": "first.png", "threshold": 0.99},
                        {"file": "second.png", "threshold": 0.99},
                    ],
                    "attempts": 1,
                    "click_count": 3,
                    "click_interval": 0,
                    "branches": {"1": [branch.to_dict()]},
                },
            )

            result = run_find_and_multi_tap(step, context)

        self.assertTrue(result.success)
        self.assertTrue(result.restart)
        self.assertEqual([], device.taps)

    def test_matched_template_without_branch_still_taps(self) -> None:
        random = np.random.default_rng(35)
        screen = random.integers(0, 255, (80, 100, 3), dtype=np.uint8)
        first = screen[20:40, 30:55].copy()
        second = random.integers(0, 255, (12, 16, 3), dtype=np.uint8)

        with TemporaryDirectory() as directory:
            template_dir = Path(directory)
            save_image(template_dir / "first.png", first)
            save_image(template_dir / "second.png", second)
            device = FakeDevice(screen)
            context = make_context(device, template_dir, engine=StepEngine(REGISTRY))
            step = Step(
                name="find",
                kind="find_and_tap",
                params={
                    "templates": [
                        {"file": "first.png", "threshold": 0.99},
                        {"file": "second.png", "threshold": 0.99},
                    ],
                    "attempts": 1,
                    "branches": {"1": []},
                    "custom_click": True,
                    "click_x": 12,
                    "click_y": 13,
                },
            )

            result = run_find_and_tap(step, context)

        self.assertTrue(result.success)
        self.assertFalse(result.restart)
        self.assertEqual([(12, 13)], device.taps)

    def test_branch_failure_fails_step(self) -> None:
        random = np.random.default_rng(37)
        screen = random.integers(0, 255, (80, 100, 3), dtype=np.uint8)
        template = screen[20:40, 30:55].copy()

        def boom(_step: Step, _context: RuntimeContext):
            return StepResult(False, "boom")

        registry = StepRegistry()
        for definition in REGISTRY.all():
            registry.register(definition)
        registry.register(
            StepDefinition(key="boom", label="Boom", fields=(), runner=boom)
        )

        with TemporaryDirectory() as directory:
            template_dir = Path(directory)
            save_image(template_dir / "target.png", template)
            device = FakeDevice(screen)
            context = make_context(device, template_dir, engine=StepEngine(registry))
            branch = Step(name="炸", kind="boom")
            step = Step(
                name="find",
                kind="find_and_tap",
                params={
                    "templates": [{"file": "target.png", "threshold": 0.99}],
                    "attempts": 1,
                    "branches": {"0": [branch.to_dict()]},
                },
            )

            result = run_find_and_tap(step, context)

        self.assertFalse(result.success)
        self.assertIn("分支", result.message)
        self.assertFalse(result.restart)

    def test_branch_of_unmatched_template_does_not_run(self) -> None:
        random = np.random.default_rng(41)
        screen = random.integers(0, 255, (80, 100, 3), dtype=np.uint8)
        first = screen[20:40, 30:55].copy()
        second = random.integers(0, 255, (12, 16, 3), dtype=np.uint8)

        with TemporaryDirectory() as directory:
            template_dir = Path(directory)
            save_image(template_dir / "first.png", first)
            save_image(template_dir / "second.png", second)
            device = FakeDevice(screen)
            context = make_context(device, template_dir, engine=StepEngine(REGISTRY))
            branch = Step(name="等待", kind="wait", params={"seconds": 0})
            step = Step(
                name="find",
                kind="find_and_tap",
                params={
                    "templates": [
                        {"file": "first.png", "threshold": 0.99},
                        {"file": "second.png", "threshold": 0.99},
                    ],
                    "attempts": 1,
                    "branches": {"1": [branch.to_dict()]},
                    "custom_click": True,
                    "click_x": 14,
                    "click_y": 15,
                },
            )

            result = run_find_and_tap(step, context)

        self.assertTrue(result.success)
        self.assertFalse(result.restart)
        self.assertEqual([(14, 15)], device.taps)

    def test_require_all_fails_when_only_some_templates_match(self) -> None:
        random = np.random.default_rng(43)
        screen = random.integers(0, 255, (80, 100, 3), dtype=np.uint8)
        first = screen[20:40, 30:55].copy()
        second = random.integers(0, 255, (12, 16, 3), dtype=np.uint8)

        with TemporaryDirectory() as directory:
            template_dir = Path(directory)
            save_image(template_dir / "first.png", first)
            save_image(template_dir / "second.png", second)
            device = FakeDevice(screen)
            context = make_context(device, template_dir)
            step = Step(
                name="find",
                kind="find_and_tap",
                params={
                    "templates": [
                        {"file": "first.png", "threshold": 0.99},
                        {"file": "second.png", "threshold": 0.99},
                    ],
                    "require_all": True,
                    "attempts": 1,
                    "custom_click": True,
                    "click_x": 16,
                    "click_y": 17,
                },
            )

            result = run_find_and_tap(step, context)

        self.assertFalse(result.success)
        self.assertEqual([], device.taps)

    def test_require_all_succeeds_when_every_template_matches(self) -> None:
        random = np.random.default_rng(47)
        screen = random.integers(0, 255, (100, 120, 3), dtype=np.uint8)
        upper = random.integers(0, 255, (10, 14, 3), dtype=np.uint8)
        lower = random.integers(0, 255, (12, 16, 3), dtype=np.uint8)
        screen[15:25, 80:94] = upper
        screen[60:72, 10:26] = lower

        with TemporaryDirectory() as directory:
            template_dir = Path(directory)
            save_image(template_dir / "upper.png", upper)
            save_image(template_dir / "lower.png", lower)
            device = FakeDevice(screen)
            context = make_context(device, template_dir)
            step = Step(
                name="find",
                kind="find_and_tap",
                params={
                    "templates": [
                        {"file": "upper.png", "threshold": 0.99},
                        {"file": "lower.png", "threshold": 0.99},
                    ],
                    "require_all": True,
                    "attempts": 1,
                    "custom_click": True,
                    "click_x": 16,
                    "click_y": 17,
                },
            )

            result = run_find_and_tap(step, context)

        self.assertTrue(result.success)
        self.assertEqual([(16, 17)], device.taps)

    def test_run_preset_executes_steps_once_ignoring_sub_loop_count(self) -> None:
        sub = Preset(
            name="子预设",
            loop_count=0,
            steps=[Step(name="子步骤", kind="wait", params={"seconds": 0})],
        )
        engine = StepEngine(REGISTRY)
        context = make_context(
            FakeDevice(np.zeros((80, 100, 3), dtype=np.uint8)),
            Path("templates"),
            engine=engine,
            presets={sub.id: sub},
        )
        step = Step(
            name="执行子预设",
            kind="run_preset",
            params={"preset_id": sub.id, "preset_name": sub.name},
        )

        result = run_run_preset(step, context)

        self.assertTrue(result.success)
        self.assertIn("子预设", result.message)

    def test_branch_step_returns_to_main_step(self) -> None:
        random = np.random.default_rng(71)
        screen = random.integers(0, 255, (80, 100, 3), dtype=np.uint8)
        template = screen[20:40, 30:55].copy()
        calls: list[str] = []
        counts = {"A": 0}

        def gate(step: Step, _context: RuntimeContext) -> StepResult:
            calls.append(step.name)
            if step.name == "A":
                counts["A"] += 1
                return StepResult(counts["A"] < 2, "识别失败")
            return StepResult(True, "ok")

        registry = StepRegistry()
        for definition in REGISTRY.all():
            registry.register(definition)
        registry.register(
            StepDefinition(
                key="gate", label="Gate", fields=(), runner=gate, can_fail=True
            )
        )

        with TemporaryDirectory() as directory:
            template_dir = Path(directory)
            save_image(template_dir / "target.png", template)
            device = FakeDevice(screen)
            context = make_context(device, template_dir, engine=StepEngine(registry))
            a = Step(name="A", kind="gate", on_failure="stop")
            branch_x = Step(name="x", kind="gate")
            branch_y = Step(name="y", kind="gate")
            branch_y.params["return_to"] = a.id
            b = Step(
                name="find",
                kind="find_and_tap",
                params={
                    "templates": [{"file": "target.png", "threshold": 0.99}],
                    "attempts": 1,
                    "branches": {"0": [branch_x.to_dict(), branch_y.to_dict()]},
                },
            )
            c = Step(name="C", kind="gate")
            preset = Preset(name="branch-return", steps=[a, b, c])

            report = StepEngine(registry).run(preset, context)

        self.assertEqual("failed", report.status)
        self.assertEqual(["A", "x", "y", "A"], calls)
        self.assertNotIn("C", calls)

    def test_run_preset_step_returns_to_outer_step(self) -> None:
        calls: list[str] = []
        counts = {"A": 0}

        def gate(step: Step, _context: RuntimeContext) -> StepResult:
            calls.append(step.name)
            if step.name == "A":
                counts["A"] += 1
                return StepResult(counts["A"] < 2, "识别失败")
            return StepResult(True, "ok")

        registry = StepRegistry()
        for definition in REGISTRY.all():
            registry.register(definition)
        registry.register(
            StepDefinition(
                key="gate", label="Gate", fields=(), runner=gate, can_fail=True
            )
        )
        a = Step(name="A", kind="gate", on_failure="stop")
        sub_a = Step(name="s1", kind="gate")
        sub_a.params["return_to"] = a.id
        sub = Preset(name="子预设", steps=[sub_a])
        engine = StepEngine(registry)
        context = make_context(
            FakeDevice(np.zeros((80, 100, 3), dtype=np.uint8)),
            Path("templates"),
            engine=engine,
            presets={sub.id: sub},
        )
        preset = Preset(
            name="outer",
            steps=[
                a,
                Step(
                    name="run",
                    kind="run_preset",
                    params={"preset_id": sub.id, "preset_name": sub.name},
                ),
                Step(name="C", kind="gate"),
            ],
        )

        report = engine.run(preset, context)

        self.assertEqual("failed", report.status)
        self.assertEqual(["A", "s1", "A"], calls)
        self.assertNotIn("C", calls)

    def test_run_preset_detects_cycle(self) -> None:
        sub = Preset(name="循环预设")
        engine = StepEngine(REGISTRY)
        context = make_context(
            FakeDevice(np.zeros((80, 100, 3), dtype=np.uint8)),
            Path("templates"),
            engine=engine,
            presets={sub.id: sub},
        )
        context.preset_path = ((sub.id, sub.name),)
        step = Step(
            name="执行预设",
            kind="run_preset",
            params={"preset_id": sub.id, "preset_name": sub.name},
        )

        runner = run_run_preset
        result = runner(step, context)

        self.assertFalse(result.success)
        self.assertIn("循环", result.message)

    def test_run_preset_missing_target_fails(self) -> None:
        engine = StepEngine(REGISTRY)
        context = make_context(
            FakeDevice(np.zeros((80, 100, 3), dtype=np.uint8)),
            Path("templates"),
            engine=engine,
            presets={},
        )
        step = Step(
            name="执行预设",
            kind="run_preset",
            params={"preset_id": "ghost", "preset_name": "幽灵"},
        )

        runner = run_run_preset
        result = runner(step, context)

        self.assertFalse(result.success)
        self.assertIn("找不到预设", result.message)

    def test_run_preset_step_runs_within_engine_flow(self) -> None:
        sub = Preset(
            name="子预设",
            steps=[Step(name="子步骤", kind="wait", params={"seconds": 0})],
        )
        engine = StepEngine(REGISTRY)
        context = make_context(
            FakeDevice(np.zeros((80, 100, 3), dtype=np.uint8)),
            Path("templates"),
            engine=engine,
            presets={sub.id: sub},
        )
        preset = Preset(
            name="父预设",
            steps=[
                Step(
                    name="执行子预设",
                    kind="run_preset",
                    params={"preset_id": sub.id, "preset_name": sub.name},
                ),
                Step(name="后续", kind="wait", params={"seconds": 0}),
            ],
        )

        report = engine.run(preset, context)

        self.assertEqual("completed", report.status)


class RecognitionPerformanceAndRoiTests(unittest.TestCase):
    def test_retries_convert_each_screenshot_once_and_reuse_template_gray_between_runs(self):
        random = np.random.default_rng(103)
        screen = random.integers(0, 255, (80, 100, 3), dtype=np.uint8)
        vision.clear_template_cache()
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            for name in ("one.png", "two.png"):
                save_image(folder / name, random.integers(0, 255, (10, 12, 3), dtype=np.uint8))
            step = Step(name="find", kind="find_and_tap", params={
                "templates": [{"file": "one.png"}, {"file": "two.png"}],
                "attempts": 3, "interval": 0})
            with (patch("model_automation.steps.find_template", return_value=None) as match,
                  patch.object(vision.cv2, "cvtColor", wraps=cv2.cvtColor) as convert,
                  patch.object(vision.cv2, "imdecode", wraps=cv2.imdecode) as decode):
                for _run in range(2):
                    result = run_find_and_tap(step, make_context(FakeDevice(screen), folder))
                    self.assertFalse(result.success)
                self.assertEqual(2, decode.call_count)
                self.assertEqual(8, convert.call_count)  # 2 templates + 6 screenshots
                self.assertEqual(12, match.call_count)
                self.assertTrue(all(len(call.args) == 3 for call in match.call_args_list))
                self.assertTrue(all(call.args[0].ndim == call.args[1].ndim == 2
                                    for call in match.call_args_list))
        vision.clear_template_cache()

    def test_legacy_loader_and_three_argument_matcher_mocks_still_work(self):
        screen = np.zeros((80, 100, 3), np.uint8)
        with (patch("model_automation.steps.load_image", return_value=np.zeros((10, 12, 3), np.uint8)),
              patch("model_automation.steps.find_template",
                    side_effect=lambda _screen, _template, _threshold: vision.Match(20, 30, 0.95))):
            device = FakeDevice(screen)
            result = run_find_and_tap(Step(name="find", kind="find_and_tap", params={
                "templates": [{"file": "mock.png"}]}), make_context(device, Path("templates")))
        self.assertTrue(result.success)
        self.assertEqual([(20, 30)], device.taps)

    def test_roi_restores_device_coordinates_and_excludes_outside_match(self):
        random = np.random.default_rng(107)
        screen = random.integers(0, 255, (80, 100, 3), dtype=np.uint8)
        template = random.integers(0, 255, (10, 12, 3), dtype=np.uint8)
        screen[5:15, 2:14] = template
        screen[60:70, 80:92] = template
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            save_image(folder / "target.png", template)
            for enabled, expected in ((True, (86, 65)), (False, (8, 10))):
                with self.subTest(enabled=enabled):
                    device = FakeDevice(screen)
                    step = Step(name="find", kind="find_and_tap", params={
                        "templates": [{"file": "target.png", "threshold": 0.99}],
                        "roi_enabled": enabled, "search_x": 75, "search_y": 55,
                        "search_width": 25, "search_height": 25})
                    result = run_find_and_tap(step, make_context(device, folder))
                    self.assertTrue(result.success, result.message)
                    self.assertEqual([expected], device.taps)
            device = FakeDevice(screen)
            step.params.update(roi_enabled=True, search_x=30, search_y=25,
                               search_width=20, search_height=20)
            self.assertFalse(run_find_and_tap(step, make_context(device, folder)).success)
            self.assertEqual([], device.taps)

    def test_invalid_roi_returns_failure_without_any_click_retry_or_branch(self):
        random = np.random.default_rng(109)
        screen = random.integers(0, 255, (80, 100, 3), dtype=np.uint8)
        cases = [(0, 0, 0, 10), (0, 0, 10, 0), (-1, 0, 10, 10),
                 (90, 70, 11, 10), (90, 70, 10, 11), (100, 80, 1, 1)]
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            save_image(folder / "target.png", screen[5:15, 2:14])
            for x, y, width, height in cases:
                with self.subTest(bounds=(x, y, width, height)):
                    device = FakeDevice(screen)
                    step = Step(name="find", kind="find_and_tap", params={
                        "templates": [{"file": "target.png"}], "roi_enabled": True,
                        "search_x": x, "search_y": y, "search_width": width,
                        "search_height": height, "attempts": 0, "tap_between": True,
                        "swipe_between": True})
                    result = run_find_and_tap(step, make_context(device, folder))
                    self.assertFalse(result.success)
                    self.assertTrue("ROI" in result.message or "search_" in result.message)
                    self.assertEqual([], device.actions)

    def test_multiple_templates_choose_spatial_first_center_with_roi(self):
        random = np.random.default_rng(113)
        screen = random.integers(0, 255, (80, 100, 3), dtype=np.uint8)
        with TemporaryDirectory() as directory:
            folder = Path(directory)
            save_image(folder / "lower.png", screen[60:70, 30:42])
            save_image(folder / "upper.png", screen[30:40, 70:82])
            device = FakeDevice(screen)
            step = Step(name="find", kind="find_and_tap", params={
                "templates": [{"file": "lower.png", "threshold": 0.99},
                              {"file": "upper.png", "threshold": 0.99}],
                "roi_enabled": True, "search_x": 25, "search_y": 25,
                "search_width": 60, "search_height": 50, "require_all": True})
            result = run_find_and_tap(step, make_context(device, folder))
            self.assertTrue(result.success, result.message)
            self.assertEqual([(76, 35)], device.taps)


class RecognitionStopTests(unittest.TestCase):
    def test_stop_during_screenshot_skips_matching_and_device_actions(self):
        device = FakeDevice(np.zeros((80, 100, 3), np.uint8))
        context = make_context(device, Path("templates"))
        def screenshot():
            context.stop_event.set()
            return device.screen.copy()
        step = Step(name="find", kind="find_and_tap", params={
            "templates": [{"file": "mock.png"}], "attempts": 0,
            "tap_between": True, "swipe_between": True})
        with patch.object(device, "screenshot", side_effect=screenshot), \
             patch("model_automation.steps.load_image", return_value=np.zeros((10, 12, 3), np.uint8)), \
             patch("model_automation.steps.find_template") as match:
            result = run_find_and_tap(step, context)
        self.assertEqual("执行已停止", result.message)
        match.assert_not_called()
        self.assertEqual([], device.actions)

    def test_stop_during_matching_skips_remaining_templates_and_actions(self):
        for found in (None, vision.Match(20, 30, 0.95)):
            with self.subTest(found=found):
                device = FakeDevice(np.zeros((80, 100, 3), np.uint8))
                context = make_context(device, Path("templates"))
                def match(*_args):
                    context.stop_event.set()
                    return found
                step = Step(name="find", kind="find_and_tap", params={
                    "templates": [{"file": "one.png"}, {"file": "two.png"}],
                    "attempts": 0, "tap_between": True, "swipe_between": True})
                with patch("model_automation.steps.load_image", return_value=np.zeros((10, 12, 3), np.uint8)), \
                     patch("model_automation.steps.find_template", side_effect=match) as matching:
                    result = run_find_and_tap(step, context)
                self.assertEqual("执行已停止", result.message)
                matching.assert_called_once()
                self.assertEqual([], device.actions)

    def test_stop_during_final_match_prevents_click(self):
        device = FakeDevice(np.zeros((80, 100, 3), np.uint8))
        context = make_context(device, Path("templates"))
        def match(*_args):
            context.stop_event.set()
            return vision.Match(20, 30, 0.95)
        with patch("model_automation.steps.load_image", return_value=np.zeros((10, 12, 3), np.uint8)), \
             patch("model_automation.steps.find_template", side_effect=match):
            result = run_find_and_tap(Step(name="find", kind="find_and_tap", params={
                "templates": [{"file": "mock.png"}]}), context)
        self.assertEqual("执行已停止", result.message)
        self.assertEqual([], device.actions)

    def test_stop_during_retry_tap_prevents_following_swipe(self):
        device = FakeDevice(np.zeros((80, 100, 3), np.uint8))
        context = make_context(device, Path("templates"))
        tap = device.tap
        def stop_after_tap(x, y):
            tap(x, y)
            context.stop_event.set()
        step = Step(name="find", kind="find_and_tap", params={
            "templates": [{"file": "mock.png"}], "attempts": 0,
            "tap_between": True, "swipe_between": True})
        with patch.object(device, "tap", side_effect=stop_after_tap), \
             patch("model_automation.steps.load_image", return_value=np.zeros((10, 12, 3), np.uint8)), \
             patch("model_automation.steps.find_template", return_value=None):
            result = run_find_and_tap(step, context)
        self.assertEqual("执行已停止", result.message)
        self.assertEqual(["tap"], [action for action, _ in device.actions])

    def test_stop_between_zero_interval_clicks_prevents_next_click(self):
        device = FakeDevice(np.zeros((80, 100, 3), np.uint8))
        context = make_context(device, Path("templates"))
        # Simulate stop arriving immediately after an interruptible wait returns.
        def wait(_seconds):
            context.stop_event.set()
            return True
        with patch("model_automation.steps.load_image", return_value=np.zeros((10, 12, 3), np.uint8)), \
             patch("model_automation.steps.find_template", return_value=vision.Match(20, 30, 0.95)), \
             patch.object(context, "wait", side_effect=wait):
            result = run_find_and_tap(Step(name="multi", kind="find_and_tap", params={
                "templates": [{"file": "mock.png"}], "tap_mode": "multi",
                "click_count": 3, "click_interval": 0}), context)
        self.assertEqual("执行已停止", result.message)
        self.assertEqual([(20, 30)], device.taps)

    def test_stopped_direct_device_steps_do_not_start_actions(self):
        for kind in ("tap", "swipe"):
            with self.subTest(kind=kind):
                device = FakeDevice(np.zeros((80, 100, 3), np.uint8))
                context = make_context(device, Path("templates"))
                context.stop_event.set()
                result = REGISTRY.get(kind).runner(Step(name=kind, kind=kind), context)
                self.assertEqual("执行已停止", result.message)
                self.assertEqual([], device.actions)


class InfiniteRetryTests(unittest.TestCase):
    class DelayedDevice(FakeDevice):
        def __init__(self, base: np.ndarray, appears_after: int) -> None:
            super().__init__(base.copy())
            self.base = base
            self.appears_after = appears_after
            self.shots = 0

        def screenshot(self) -> np.ndarray:
            self.shots += 1
            if self.shots >= self.appears_after:
                return self.base.copy()
            return np.zeros_like(self.base)

    def test_zero_attempts_retries_until_template_appears(self) -> None:
        random = np.random.default_rng(61)
        screen = random.integers(0, 255, (80, 100, 3), dtype=np.uint8)
        template = random.integers(0, 255, (12, 16, 3), dtype=np.uint8)
        screen[40:52, 60:76] = template

        with TemporaryDirectory() as directory:
            template_dir = Path(directory)
            save_image(template_dir / "late.png", template)
            device = self.DelayedDevice(screen, appears_after=3)
            context = make_context(device, template_dir)
            step = Step(
                name="find",
                kind="find_and_tap",
                params={
                    "templates": [{"file": "late.png", "threshold": 0.99}],
                    "attempts": 0,
                    "interval": 0,
                    "custom_click": True,
                    "click_x": 18,
                    "click_y": 19,
                },
            )

            result = run_find_and_tap(step, context)

        self.assertTrue(result.success)
        self.assertEqual(3, device.shots)
        self.assertEqual([(18, 19)], device.taps)

    def test_zero_attempts_stops_on_stop_event(self) -> None:
        random = np.random.default_rng(67)
        screen = random.integers(0, 255, (80, 100, 3), dtype=np.uint8)
        template = random.integers(0, 255, (12, 16, 3), dtype=np.uint8)
        stop_event = Event()

        class StoppingDevice(FakeDevice):
            def screenshot(self) -> np.ndarray:
                stop_event.set()
                return np.zeros_like(screen)

        with TemporaryDirectory() as directory:
            template_dir = Path(directory)
            save_image(template_dir / "never.png", template)
            device = StoppingDevice(screen)
            context = RuntimeContext(
                device=device,
                template_dir=template_dir,
                stop_event=stop_event,
                log=lambda _message: None,
            )
            step = Step(
                name="find",
                kind="find_and_tap",
                params={
                    "templates": [{"file": "never.png", "threshold": 0.99}],
                    "attempts": 0,
                    "interval": 0,
                },
            )

            result = run_find_and_tap(step, context)

        self.assertFalse(result.success)
        self.assertIn("执行已停止", result.message)
        self.assertEqual([], device.taps)


class EndLoopTests(unittest.TestCase):
    def test_end_loop_skips_remaining_steps_and_starts_next_cycle(self) -> None:
        logs: list[str] = []
        engine = StepEngine(REGISTRY)
        preset = Preset(
            name="end_loop",
            loop_count=3,
            steps=[
                Step(name="步骤一", kind="wait", params={"seconds": 0}),
                Step(name="结束本轮", kind="end_loop"),
                Step(name="步骤三", kind="wait", params={"seconds": 0}),
            ],
        )
        context = RuntimeContext(
            device=FakeDevice(np.zeros((80, 100, 3), dtype=np.uint8)),
            template_dir=Path("templates"),
            stop_event=Event(),
            log=logs.append,
            engine=engine,
        )

        report = engine.run(preset, context)

        self.assertEqual("completed", report.status)
        self.assertEqual(3, sum(1 for line in logs if "[1/3]" in line))
        self.assertEqual(3, sum(1 for line in logs if "[2/3]" in line))
        self.assertEqual(0, sum(1 for line in logs if "[3/3]" in line))

    def test_end_loop_on_single_loop_finishes_whole_run(self) -> None:
        logs: list[str] = []
        engine = StepEngine(REGISTRY)
        preset = Preset(
            name="once",
            loop_count=1,
            steps=[
                Step(name="步骤一", kind="wait", params={"seconds": 0}),
                Step(name="结束本轮", kind="end_loop"),
                Step(name="步骤三", kind="wait", params={"seconds": 0}),
            ],
        )
        context = RuntimeContext(
            device=FakeDevice(np.zeros((80, 100, 3), dtype=np.uint8)),
            template_dir=Path("templates"),
            stop_event=Event(),
            log=logs.append,
            engine=engine,
        )

        report = engine.run(preset, context)

        self.assertEqual("completed", report.status)
        self.assertEqual(1, sum(1 for line in logs if "[1/3]" in line))
        self.assertEqual(1, sum(1 for line in logs if "[2/3]" in line))
        self.assertEqual(0, sum(1 for line in logs if "[3/3]" in line))


class RuntimeValidationTests(unittest.TestCase):
    def test_invalid_fields_fail_before_any_device_action(self):
        cases = [
            ("tap", {"wait_after": "bad"}),
            ("tap", {"x": 1.5}),
            ("tap", {"y": True}),
            ("swipe", {"wait_after": float("inf")}),
            ("swipe", {"duration": -1}),
            ("wait", {"seconds": float("nan")}),
            ("find_and_tap", {"attempts": -1}),
            ("find_and_tap", {"wait_after": "bad"}),
            ("find_and_tap", {"require_all": "false"}),
            ("find_and_tap", {"click_count": 0}),
            ("find_and_tap", {"tap_between_x": -1}),
            ("find_and_tap", {"threshold": True}),
        ]
        class NoActionDevice:
            def __getattr__(self, name):
                raise AssertionError(f"unexpected device action: {name}")
        for kind, params in cases:
            with self.subTest(kind=kind, params=params):
                if kind == "find_and_tap":
                    params = {"templates": [{"file": "target.png", "threshold": 0.8}], **params}
                    if "threshold" in params:
                        params["templates"][0]["threshold"] = params.pop("threshold")
                result = REGISTRY.get(kind).runner(
                    Step(name="invalid", kind=kind, params=params),
                    make_context(NoActionDevice(), Path("templates")),
                )
                self.assertFalse(result.success)

    def test_tap_uses_registered_coordinate_defaults(self):
        device = FakeDevice(np.zeros((10, 10, 3), dtype=np.uint8))
        result = REGISTRY.get("tap").runner(
            Step(name="default", kind="tap"), make_context(device, Path("templates")))
        self.assertTrue(result.success)
        self.assertEqual([(540, 1000)], device.taps)

    def test_missing_or_corrupt_template_blocks_require_all_but_not_any(self):
        random = np.random.default_rng(91)
        screen = random.integers(0, 255, (80, 100, 3), dtype=np.uint8)
        with TemporaryDirectory() as directory:
            template_dir = Path(directory)
            save_image(template_dir / "target.png", screen[20:40, 30:55].copy())
            (template_dir / "corrupt.png").write_bytes(b"not an image")
            for missing in ("missing.png", "corrupt.png"):
                for require_all in (True, False):
                    with self.subTest(missing=missing, require_all=require_all):
                        device = FakeDevice(screen)
                        step = Step(name="find", kind="find_and_tap", params={
                            "templates": [{"file": "target.png"}, {"file": missing}],
                            "require_all": require_all,
                        })
                        result = run_find_and_tap(step, make_context(device, template_dir))
                        self.assertEqual(not require_all, result.success)
                        self.assertEqual([] if require_all else [(42, 30)], device.taps)


class RecordedActionsTests(unittest.TestCase):
    def test_empty_actions_fail_without_device_calls(self) -> None:
        device = FakeDevice(np.zeros((80, 100, 3), np.uint8))
        context = make_context(device, Path("templates"))

        result = run_recorded_actions(
            Step(name="recorded", kind="recorded_actions", params={"actions": []}),
            context,
        )

        self.assertFalse(result.success)
        self.assertIn("尚未录制操作", result.message)
        self.assertEqual([], device.actions)

    def test_actions_replay_in_order_with_relative_waits(self) -> None:
        device = FakeDevice(np.zeros((80, 100, 3), np.uint8))
        context = make_context(device, Path("templates"))
        waits: list[float] = []
        actions = [
            {"type": "tap", "x": 10, "y": 20, "at": 0},
            {"type": "swipe", "x1": 30, "y1": 40, "x2": 50, "y2": 60,
             "duration": 300, "at": 250},
            {"type": "tap", "x": 70, "y": 80, "at": 800},
        ]

        with patch.object(RuntimeContext, "wait", new=lambda _self, seconds: waits.append(seconds) or True):
            result = run_recorded_actions(
                Step(name="recorded", kind="recorded_actions", params={"actions": actions}),
                context,
            )

        self.assertTrue(result.success)
        self.assertEqual([0.25, 0.25], waits)
        self.assertEqual(
            [("tap", (10, 20)), ("swipe", (30, 40, 50, 60, 300)), ("tap", (70, 80))],
            device.actions,
        )

    def test_first_action_is_immediate_and_last_has_no_trailing_wait(self) -> None:
        device = FakeDevice(np.zeros((80, 100, 3), np.uint8))
        context = make_context(device, Path("templates"))
        waits: list[float] = []
        actions = [
            {"type": "swipe", "x1": 1, "y1": 2, "x2": 3, "y2": 4,
             "duration": 120, "at": 0},
        ]

        with patch.object(RuntimeContext, "wait", new=lambda _self, seconds: waits.append(seconds) or True):
            result = run_recorded_actions(
                Step(name="recorded", kind="recorded_actions", params={"actions": actions}),
                context,
            )

        self.assertTrue(result.success)
        self.assertEqual([], waits)
        self.assertEqual([("swipe", (1, 2, 3, 4, 120))], device.actions)

    def test_stop_before_first_action_prevents_device_calls(self) -> None:
        device = FakeDevice(np.zeros((80, 100, 3), np.uint8))
        context = make_context(device, Path("templates"))
        context.stop_event.set()

        result = run_recorded_actions(
            Step(name="recorded", kind="recorded_actions", params={"actions": [
                {"type": "tap", "x": 1, "y": 2, "at": 0},
            ]}),
            context,
        )

        self.assertFalse(result.success)
        self.assertIn("执行已停止", result.message)
        self.assertEqual([], device.actions)

    def test_validation_rejects_invalid_actions_and_allows_empty(self) -> None:
        definition = REGISTRY.get("recorded_actions")
        self.assertIsNotNone(definition)
        self.assertEqual({"actions": []}, definition.validate_params({}))

        invalid = [
            {"actions": "bad"},
            {"actions": [{"type": "tap", "x": True, "y": 1, "at": 0}]},
            {"actions": [{"type": "tap", "x": -1, "y": 1, "at": 0}]},
            {"actions": [{"type": "swipe", "x1": 0, "y1": 0, "x2": 1, "y2": 1,
                          "duration": 0, "at": 0}]},
            {"actions": [{"type": "swipe", "x1": 0, "y1": 0, "x2": 1, "y2": 1,
                          "duration": 5001, "at": 0}]},
            {"actions": [{"type": "tap", "x": 1, "y": 1, "at": 10}]},
            {"actions": [{"type": "tap", "x": 1, "y": 1, "at": 20},
                         {"type": "tap", "x": 2, "y": 2, "at": 10}]},
            {"actions": [{"type": "nope", "x": 1, "y": 1, "at": 0}]},
            {"actions": [{"type": "tap", "x": 1, "y": 1, "at": 0}] * 1001},
        ]
        for params in invalid:
            with self.subTest(params=str(params)[:80]), self.assertRaises(ValueError):
                definition.validate_params(params)

    def test_step_summary_reports_count_and_duration(self) -> None:
        step = Step(name="recorded", kind="recorded_actions", params={"actions": [
            {"type": "tap", "x": 10, "y": 20, "at": 0},
            {"type": "swipe", "x1": 30, "y1": 40, "x2": 50, "y2": 60,
             "duration": 300, "at": 1000},
        ]})

        self.assertEqual("2 个操作 · 1.3 秒", step_summary(step))


if __name__ == "__main__":
    unittest.main()
