from unittest.mock import patch
import unittest

import cv2
import numpy as np

from model_automation.vision import (
    ACCELERATION_CPU,
    ACCELERATION_GPU,
    acceleration_backend,
    find_template,
    fit_image_to_bounds,
    get_acceleration,
    select_point,
    select_region,
    select_swipe,
    set_acceleration,
)


class AccelerationTests(unittest.TestCase):
    def test_cpu_mode_is_restored(self) -> None:
        self.assertEqual(ACCELERATION_CPU, set_acceleration(ACCELERATION_CPU))
        self.assertEqual(ACCELERATION_CPU, get_acceleration())
        self.assertIsNone(acceleration_backend())

    def test_gpu_mode_applies_or_falls_back_to_cpu(self) -> None:
        applied = set_acceleration(ACCELERATION_GPU)
        self.assertIn(applied, {ACCELERATION_CPU, ACCELERATION_GPU})
        if applied == ACCELERATION_GPU:
            self.assertIn(acceleration_backend(), {"cuda", "ocl"})

    def test_unknown_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            set_acceleration("quantum")

    def test_matching_works_in_every_applied_mode(self) -> None:
        random = np.random.default_rng(53)
        screen = random.integers(0, 255, (80, 100, 3), dtype=np.uint8)
        template = screen[20:40, 30:55].copy()
        for mode in (ACCELERATION_CPU, ACCELERATION_GPU):
            applied = set_acceleration(mode)
            match = find_template(screen, template, 0.99)
            self.assertIsNotNone(match, f"{mode} 模式下未找到目标")
            self.assertEqual((42, 30), (match.x, match.y))
            self.assertEqual(applied, get_acceleration())
        set_acceleration(ACCELERATION_CPU)


class SelectPointTests(unittest.TestCase):
    def test_image_is_scaled_to_fit_desktop_bounds(self) -> None:
        image = np.zeros((1440, 2560, 3), dtype=np.uint8)

        display, scale = fit_image_to_bounds(image, 1280, 720)

        self.assertEqual(0.5, scale)
        self.assertEqual((720, 1280, 3), display.shape)

    def test_region_is_mapped_back_to_original_screen_coordinates(self) -> None:
        image = np.zeros((1440, 2560, 3), dtype=np.uint8)

        with (
            patch(
                "model_automation.vision.cv2.selectROI",
                return_value=(100, 200, 300, 400),
            ) as select_roi,
            patch("model_automation.vision.cv2.destroyAllWindows"),
        ):
            region = select_region("test", image, 1280, 720)

        displayed_image = select_roi.call_args.args[1]
        self.assertEqual((720, 1280, 3), displayed_image.shape)
        self.assertEqual((200, 400, 600, 800), region)

    def test_scaled_display_returns_original_screen_coordinates(self) -> None:
        image = np.zeros((1440, 2560, 3), dtype=np.uint8)
        callback: list[object] = []
        clicked = False

        def remember_callback(_title: str, handler: object) -> None:
            callback.append(handler)

        def click_once(_title: str, _canvas: np.ndarray) -> None:
            nonlocal clicked
            if not clicked:
                clicked = True
                callback[0](cv2.EVENT_LBUTTONDOWN, 100, 200, 0, None)

        with (
            patch("model_automation.vision.cv2.namedWindow"),
            patch(
                "model_automation.vision.cv2.setMouseCallback",
                side_effect=remember_callback,
            ),
            patch("model_automation.vision.cv2.imshow", side_effect=click_once),
            patch("model_automation.vision.cv2.waitKey", return_value=-1),
            patch("model_automation.vision.cv2.destroyWindow"),
        ):
            point = select_point("test", image)

        self.assertEqual((200, 400), point)

    def test_swipe_drag_returns_original_start_and_end_coordinates(self) -> None:
        image = np.zeros((1440, 2560, 3), dtype=np.uint8)
        callback: list[object] = []
        dragged = False

        def remember_callback(_title: str, handler: object) -> None:
            callback.append(handler)

        def drag_once(_title: str, _canvas: np.ndarray) -> None:
            nonlocal dragged
            if not dragged:
                dragged = True
                callback[0](cv2.EVENT_LBUTTONDOWN, 100, 200, 0, None)
                callback[0](cv2.EVENT_MOUSEMOVE, 300, 400, 0, None)
                callback[0](cv2.EVENT_LBUTTONUP, 300, 400, 0, None)

        with (
            patch("model_automation.vision.cv2.namedWindow"),
            patch(
                "model_automation.vision.cv2.setMouseCallback",
                side_effect=remember_callback,
            ),
            patch("model_automation.vision.cv2.imshow", side_effect=drag_once),
            patch("model_automation.vision.cv2.waitKey", return_value=-1),
            patch("model_automation.vision.cv2.destroyWindow"),
        ):
            swipe = select_swipe("test", image, 1280, 720)

        self.assertEqual((200, 400, 600, 800), swipe)


if __name__ == "__main__":
    unittest.main()
