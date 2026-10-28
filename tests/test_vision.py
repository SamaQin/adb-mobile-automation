from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import os
import unittest

import cv2
import numpy as np

from model_automation import vision
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


class TemplateCacheTests(unittest.TestCase):
    def setUp(self):
        vision.clear_template_cache()

    def tearDown(self):
        vision.clear_template_cache()

    def test_decode_and_gray_are_shared_by_resolved_path_across_threads(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "target.png"
            vision.save_image(path, np.full((20, 30, 3), 73, np.uint8))
            alias = path.parent / ".." / path.parent.name / path.name
            with (patch.object(vision.cv2, "imdecode", wraps=cv2.imdecode) as decode,
                  patch.object(vision.cv2, "cvtColor", wraps=cv2.cvtColor) as convert,
                  ThreadPoolExecutor(max_workers=8) as executor):
                results = list(executor.map(
                    lambda index: vision.load_template(path if index % 2 else alias,
                                                       grayscale=bool(index % 2)), range(24)))
            self.assertEqual(1, decode.call_count)
            self.assertEqual(1, convert.call_count)
            self.assertTrue(all(result is not None for result in results))
            for image in results[:2]:
                with self.assertRaises(ValueError):
                    image.flat[0] = 0
                with self.assertRaises(ValueError):
                    image.setflags(write=True)
            self.assertEqual(73, int(vision.load_template(path)[0, 0, 0]))
            editable = vision.load_image(path)
            editable[:] = 0
            self.assertEqual(73, int(vision.load_template(path)[0, 0, 0]))

    def test_external_overwrite_invalidates_by_mtime_and_size_and_deletion(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "target.bmp"
            vision.save_image(path, np.full((8, 8, 3), 20, np.uint8))
            first = vision.load_template(path, grayscale=True)
            initial = path.stat()
            vision.save_image(path, np.full((8, 8, 3), 90, np.uint8))
            os.utime(path, ns=(initial.st_atime_ns, initial.st_mtime_ns + 1_000_000))
            second = vision.load_template(path, grayscale=True)
            self.assertEqual(90, int(second[0, 0]))
            self.assertIsNot(first, second)
            changed = path.stat()
            vision.save_image(path, np.full((9, 8, 3), 120, np.uint8))
            os.utime(path, ns=(changed.st_atime_ns, changed.st_mtime_ns))
            self.assertEqual((9, 8), vision.load_template(path, grayscale=True).shape)
            path.write_bytes(b"corrupt")
            self.assertIsNone(vision.load_template(path))
            path.unlink()
            self.assertIsNone(vision.load_template(path))
            self.assertEqual(0, len(vision._TEMPLATE_CACHE))
            self.assertEqual(0, vision._TEMPLATE_CACHE_BYTES)

    def test_lru_limits_entries_and_bytes_and_skips_oversized_templates(self):
        with TemporaryDirectory() as directory:
            paths = [Path(directory) / f"{index}.png" for index in range(4)]
            for path in paths:
                vision.save_image(path, np.zeros((10, 10, 3), np.uint8))
            with (patch.object(vision, "TEMPLATE_CACHE_MAX_ENTRIES", 2),
                  patch.object(vision, "TEMPLATE_CACHE_MAX_BYTES", 800),
                  patch.object(vision.cv2, "imdecode", wraps=cv2.imdecode) as decode):
                for path in paths[:2]:
                    vision.load_template(path)
                vision.load_template(paths[0])  # refresh first entry
                vision.load_template(paths[2])
                self.assertEqual([paths[0].resolve(), paths[2].resolve()], list(vision._TEMPLATE_CACHE))
                vision.load_template(paths[1])  # second entry was evicted
                self.assertEqual(4, decode.call_count)
                self.assertLessEqual(vision._TEMPLATE_CACHE_BYTES, 800)
            vision.clear_template_cache()
            with patch.object(vision, "TEMPLATE_CACHE_MAX_BYTES", 399):
                self.assertIsNotNone(vision.load_template(paths[0]))
                self.assertEqual(0, len(vision._TEMPLATE_CACHE))
            with patch.object(vision, "TEMPLATE_CACHE_MAX_BYTES", 400):
                vision.load_template(paths[0])
                vision.load_template(paths[1])
                self.assertEqual(1, len(vision._TEMPLATE_CACHE))
                self.assertEqual(400, vision._TEMPLATE_CACHE_BYTES)

    def test_empty_image_returns_none(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "empty.png"
            path.touch()
            self.assertIsNone(vision.load_template(path))

    def test_gray_matching_keeps_spatial_priority_over_score(self):
        result = np.zeros((30, 40), np.float32)
        result[2, 20] = 0.91
        result[20, 2] = 0.99
        with (patch.object(vision, "_compute_match_result", return_value=result),
              patch.object(vision.cv2, "cvtColor") as convert):
            match = find_template(np.zeros((35, 45), np.uint8), np.zeros((6, 6), np.uint8), 0.9)
        convert.assert_not_called()
        self.assertEqual((23, 5), (match.x, match.y))


class AccelerationTests(unittest.TestCase):
    def tearDown(self):
        set_acceleration(ACCELERATION_CPU)

    def test_opencl_probe_rejects_disabled_context_and_cpu_device(self):
        with (patch.object(cv2.ocl, 'setUseOpenCL'),
              patch.object(cv2.ocl, 'haveOpenCL', return_value=True),
              patch.object(cv2.ocl, 'useOpenCL', return_value=False),
              patch.object(cv2, 'matchTemplate') as matcher):
            self.assertFalse(vision._probe_opencl())
            matcher.assert_not_called()
        device = Mock()
        device.type.return_value = cv2.ocl.Device_TYPE_CPU
        with (patch.object(cv2.ocl, 'setUseOpenCL'),
              patch.object(cv2.ocl, 'haveOpenCL', return_value=True),
              patch.object(cv2.ocl, 'useOpenCL', return_value=True),
              patch.object(cv2.ocl, 'Device_getDefault', return_value=device),
              patch.object(cv2, 'matchTemplate') as matcher):
            self.assertFalse(vision._probe_opencl())
            matcher.assert_not_called()

    def test_opencl_matching_enables_gpu_in_the_executing_thread(self):
        screen = np.zeros((32, 40), np.uint8)
        template = np.zeros((8, 8), np.uint8)
        with (patch.object(vision, '_ACCELERATION', ACCELERATION_GPU),
              patch.object(vision, '_GPU_BACKEND', 'ocl'),
              patch.object(vision, '_enable_opencl_gpu', return_value=True) as enable,
              patch.object(cv2, 'matchTemplate') as matcher):
            vision._compute_match_result(screen, template)
            enable.assert_called_once()
            self.assertIsInstance(matcher.call_args.args[0], cv2.UMat)

    def test_gpu_error_downgrades_state_and_returns_cpu_result(self):
        screen = np.zeros((32, 40), np.uint8)
        template = np.zeros((8, 8), np.uint8)
        expected = np.zeros((25, 33), np.float32)
        with (patch.object(vision, '_ACCELERATION', ACCELERATION_GPU),
              patch.object(vision, '_GPU_BACKEND', 'ocl'),
              patch.object(vision, '_enable_opencl_gpu', return_value=True),
              patch.object(cv2, 'matchTemplate', side_effect=[cv2.error('GPU test failure'), expected]),
              self.assertLogs('model_automation.vision', level='WARNING') as logs):
            self.assertIs(expected, vision._compute_match_result(screen, template))
            self.assertEqual(ACCELERATION_CPU, get_acceleration())
            self.assertIsNone(acceleration_backend())
            self.assertIn('GPU test failure', logs.output[0])

    def test_cuda_probe_and_match_receive_screen_before_template(self):
        screen = np.zeros((16, 20), np.uint8)
        template = np.zeros((8, 10), np.uint8)
        matcher = Mock()
        matcher.match.return_value.download.return_value = np.zeros((9, 9), np.float32)
        with (patch.object(vision.cv2.cuda, "createTemplateMatching", return_value=matcher, create=True),
              patch.object(vision.cv2.cuda, "getCudaEnabledDeviceCount", return_value=1),
              patch.object(vision.cv2, "cuda_GpuMat", side_effect=lambda image: image)):
            self.assertTrue(vision._probe_cuda_matcher())
            first, second = matcher.match.call_args.args
            self.assertEqual((16, 16), first.shape)
            self.assertEqual((8, 8), second.shape)
            with (patch.object(vision, "_ACCELERATION", ACCELERATION_GPU),
                  patch.object(vision, "_GPU_BACKEND", "cuda"),
                  patch.object(vision, "_CUDA_MATCHER", matcher)):
                vision._compute_match_result(screen, template)
            first, second = matcher.match.call_args.args
            self.assertEqual(screen.shape, first.shape)
            self.assertEqual(template.shape, second.shape)
            self.assertEqual(np.float32, first.dtype)


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
