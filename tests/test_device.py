from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import cv2
import numpy as np

from model_automation.device import AdbClient, DeviceError


def screenshot_result(width=100, height=60):
    success, encoded = cv2.imencode('.png', np.zeros((height, width, 3), np.uint8))
    assert success
    return subprocess.CompletedProcess([], 0, encoded.tobytes(), b'')


class DeviceResolutionTests(TestCase):
    def test_fresh_screenshot_dimensions_are_reused_without_reusing_pixels(self):
        with TemporaryDirectory() as directory:
            client = AdbClient(Path(directory))
            with patch.object(client, '_run', return_value=screenshot_result()) as run:
                first = client.screenshot()
                self.assertEqual((100, 60), client.screen_resolution())
                second = client.screenshot()
                self.assertIsNot(first, second)
                self.assertEqual(2, run.call_count)

    def test_concurrent_resolution_checks_capture_once_and_expire(self):
        with TemporaryDirectory() as directory:
            client = AdbClient(Path(directory))
            with patch.object(client, '_run', return_value=screenshot_result()) as run:
                with ThreadPoolExecutor(max_workers=8) as pool:
                    results = list(pool.map(lambda _: client.screen_resolution(), range(24)))
                self.assertTrue(all(result == (100, 60) for result in results))
                self.assertEqual(1, run.call_count)
                client._resolution_at -= 1
                client.screen_resolution()
                self.assertEqual(2, run.call_count)

    def test_refresh_observes_rotation_and_disconnect_invalidates_dimensions(self):
        with TemporaryDirectory() as directory:
            client = AdbClient(Path(directory))
            with patch.object(client, '_run', side_effect=[screenshot_result(), screenshot_result(60, 100), subprocess.CompletedProcess([], 0, 'offline', '')]):
                self.assertEqual((100, 60), client.screen_resolution())
                self.assertEqual((60, 100), client.screen_resolution(refresh=True))
                self.assertEqual('offline', client.state())
                self.assertIsNone(client._resolution)

    def test_empty_or_corrupt_screenshots_report_device_error_and_clear_cache(self):
        with TemporaryDirectory() as directory:
            client = AdbClient(Path(directory))
            for payload in [b'', b'not an image']:
                with self.subTest(payload=payload), patch.object(client, '_run', return_value=subprocess.CompletedProcess([], 0, payload, b'')):
                    client._resolution = (10, 20)
                    with self.assertRaises(DeviceError):
                        client.screenshot()
                    self.assertIsNone(client._resolution)
