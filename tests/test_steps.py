from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest

import numpy as np

from model_automation.engine import RuntimeContext, StepEngine, StepResult
from model_automation.models import Preset, Step
from model_automation.registry import StepDefinition, StepRegistry
from model_automation.steps import (
    REGISTRY,
    run_find_and_multi_tap,
    run_find_and_tap,
    run_run_preset,
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


if __name__ == "__main__":
    unittest.main()
