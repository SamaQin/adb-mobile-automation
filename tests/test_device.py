from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from threading import Event
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


class DeviceSelectionTests(TestCase):
    DEVICES = ('List of devices attached\n'
               'USB123 device usb:1-1 product:phone model:Pixel_8 transport_id:1\n'
               '10.0.35.91:5555 device product:phone model:Wireless_Phone transport_id:2\n'
               '[2001:db8::1]:5555 offline transport_id:3\n'
               'unauthorized-usb unauthorized usb:1-2\n')

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.client = AdbClient(Path(self.directory.name))
        self.commands = []
        self.mock_run = patch('model_automation.device.subprocess.run', side_effect=self.run_adb).start()
        self.addCleanup(patch.stopall)

    def run_adb(self, command, **options):
        self.commands.append((command[1:], options))
        args = command[1:]
        if args[0] == 'devices':
            return subprocess.CompletedProcess(command, 0, self.DEVICES, '')
        if args[-3:] == ['exec-out', 'screencap', '-p']:
            return screenshot_result()
        if args[-1] == 'get-state':
            return subprocess.CompletedProcess(command, 0, 'device\n', '')
        return subprocess.CompletedProcess(command, 0, 'connected', '')

    def test_list_and_selected_commands_use_only_the_requested_target(self):
        devices = self.client.list_devices()
        self.assertEqual({'serial': 'USB123', 'state': 'device', 'model': 'Pixel_8', 'transport': 'usb'}, devices[0])
        self.assertEqual('wireless', devices[1]['transport'])
        self.assertEqual('wireless', devices[2]['transport'])
        self.client.select_device('10.0.35.91:5555')
        self.client.state()
        self.client.screenshot()
        self.client.tap(3, 4)
        self.client.swipe(1, 2, 3, 4)
        for command, _ in self.commands:
            if command[0] == 'devices':
                self.assertEqual(['devices', '-l'], command)
            else:
                self.assertEqual(['-s', '10.0.35.91:5555'], command[:2])
        self.assertEqual('10.0.35.91:5555', self.client.selected_serial)

    def test_select_rejects_missing_or_unavailable_devices_without_changing_target(self):
        self.client.select_device('USB123')
        self.client.screenshot()
        for serial in ['missing', 'unauthorized-usb', '[2001:db8::1]:5555', '-a']:
            with self.subTest(serial=serial), self.assertRaises(DeviceError):
                self.client.select_device(serial)
            self.assertEqual('USB123', self.client.selected_serial)
        self.client.select_device('10.0.35.91:5555')
        self.assertIsNone(self.client._resolution)

    def test_default_single_device_commands_keep_legacy_adb_selection(self):
        self.client.state()
        self.assertEqual(['get-state'], self.commands[-1][0])
        self.assertIsNone(self.client.selected_serial)

    def test_connect_verifies_available_target_and_uses_global_command(self):
        self.client.select_device('USB123')
        result = self.client.connect_wireless('10.0.35.91', 5555)
        self.assertEqual('10.0.35.91:5555', result['serial'])
        self.assertEqual(['connect', result['endpoint']], self.commands[-2][0])
        self.assertLessEqual(self.commands[-2][1]['timeout'], 20)
        self.assertEqual(['devices', '-l'], self.commands[-1][0])

    def test_failed_or_offline_connection_does_not_change_selection(self):
        self.client.select_device('USB123')
        for message in ['failed to connect: Connection refused', 'unable to connect', 'error: no route']:
            with self.subTest(message=message), patch.object(self.client, '_run', return_value=subprocess.CompletedProcess([], 0, message, '')):
                with self.assertRaisesRegex(DeviceError, message):
                    self.client.connect_wireless('10.0.35.91', 5555)
            self.assertEqual('USB123', self.client.selected_serial)
        with self.assertRaisesRegex(DeviceError, '未就绪'):
            self.client.connect_wireless('2001:db8::1', 5555)
        self.assertEqual('USB123', self.client.selected_serial)

    def test_ipv6_is_bracketed_and_matches_expanded_adb_endpoint(self):
        self.DEVICES += '[2001:0db8:0:0:0:0:0:2]:5555 device model:Phone\n'
        result = self.client.connect_wireless('2001:db8::2', 5555)
        self.assertEqual('[2001:db8::2]:5555', result['endpoint'])
        self.assertEqual('[2001:0db8:0:0:0:0:0:2]:5555', self.client.selected_serial)
        self.assertEqual(['connect', '[2001:db8::2]:5555'], self.commands[-2][0])

    def test_rejects_hostnames_options_and_invalid_ports_before_running_adb(self):
        for host, port in [('phone.local', 5555), ('127.0.0.1 -a', 5555), ('--help', 5555), ('fe80::1%2', 5555), ('127.0.0.1', True), ('127.0.0.1', '5555'), ('::1', 0), ('::1', 65536)]:
            with self.subTest(host=host, port=port), self.assertRaises(DeviceError):
                self.client.connect_wireless(host, port)
        self.mock_run.assert_not_called()

    def test_pair_passes_code_only_via_stdin_and_never_selects_device(self):
        self.client.select_device('USB123')
        result = self.client.pair_wireless('::1', 37001, '012345')
        command, options = self.commands[-1]
        self.assertEqual(['pair', '[::1]:37001'], command)
        self.assertNotIn('012345', repr(command))
        self.assertEqual('012345\n', options['input'])
        self.assertLessEqual(options['timeout'], 30)
        self.assertNotIn('serial', result)
        self.assertEqual('USB123', self.client.selected_serial)
        self.assertNotIn('012345', repr(self.client.__dict__))
        for code in ['12345', '1234567', 123456, '１２３４５６']:
            with self.subTest(code=code), self.assertRaises(DeviceError):
                self.client.pair_wireless('::1', 37001, code)

    def test_pair_supports_adb_host_port_syntax_without_code_in_arguments(self):
        replies = [subprocess.CompletedProcess([], 1, '', 'usage: adb pair HOST PORT'),
                   subprocess.CompletedProcess([], 0, 'Successfully paired', '')]
        with patch('model_automation.device.subprocess.run', side_effect=replies) as run:
            self.client.pair_wireless('2001:db8::1', 37001, '012345')
        self.assertEqual(['pair', '2001:db8::1', '37001'], run.call_args.args[0][1:])
        for call in run.call_args_list:
            self.assertNotIn('012345', repr(call.args))
            self.assertEqual('012345\n', call.kwargs['input'])

    def test_network_timeout_is_bounded_and_does_not_change_selected_target(self):
        self.client.select_device('USB123')
        with patch('model_automation.device.subprocess.run', side_effect=subprocess.TimeoutExpired(['adb', 'connect'], 15)) as run:
            with self.assertRaisesRegex(DeviceError, 'ADB 命令失败'):
                self.client.connect_wireless('10.0.35.91', 5555)
        self.assertLessEqual(run.call_args.kwargs['timeout'], 20)
        self.assertEqual('USB123', self.client.selected_serial)
        with patch('model_automation.device.subprocess.run', side_effect=subprocess.TimeoutExpired(['adb', 'pair'], 20)):
            with self.assertRaises(DeviceError) as error:
                self.client.pair_wireless('10.0.35.91', 37001, '012345')
        self.assertNotIn('012345', str(error.exception))

    def test_pair_errors_and_success_output_redact_code(self):
        for returncode in [0, 1]:
            with patch.object(self.client, '_run', return_value=subprocess.CompletedProcess([], returncode, 'failed to pair with 012345: wrong code', '')):
                with self.assertRaises(DeviceError) as error:
                    self.client.pair_wireless('127.0.0.1', 37001, '012345')
                self.assertNotIn('012345', str(error.exception))
                self.assertIn('wrong code', str(error.exception))
        with patch.object(self.client, '_run', return_value=subprocess.CompletedProcess([], 0, 'Successfully paired 012345', '')):
            result = self.client.pair_wireless('127.0.0.1', 37001, '012345')
        self.assertNotIn('012345', result['message'])
        with patch.object(self.client, '_run', side_effect=DeviceError('timeout: 012345')):
            with self.assertRaises(DeviceError) as error:
                self.client.pair_wireless('::1', 37001, '012345')
        self.assertNotIn('012345', str(error.exception))

    def test_enable_wireless_targets_selected_usb_and_never_connects(self):
        self.client.select_device('USB123')
        self.client.screenshot()
        result = self.client.enable_wireless()
        self.assertEqual({'message': 'connected', 'port': 5555, 'serial': 'USB123'}, result)
        self.assertEqual(['-s', 'USB123', 'tcpip', '5555'], self.commands[-1][0])
        self.assertEqual('USB123', self.client.selected_serial)
        self.assertIsNone(self.client._resolution)
        self.assertFalse(any(command[0] == 'connect' for command, _ in self.commands))

    def test_enable_wireless_pins_only_available_usb_in_default_mode(self):
        self.DEVICES = 'List of devices attached\nUSB123 device model:Phone\n'
        self.client.enable_wireless(4567)
        self.assertEqual(['-s', 'USB123', 'tcpip', '4567'], self.commands[-1][0])
        self.assertEqual('USB123', self.client.selected_serial)

    def test_enable_wireless_rejects_ambiguous_offline_and_wireless_targets(self):
        with self.assertRaisesRegex(DeviceError, 'USB'):
            self.client.enable_wireless()
        self.client.select_device('10.0.35.91:5555')
        with self.assertRaisesRegex(DeviceError, 'USB'):
            self.client.enable_wireless()
        self.client.select_device('USB123')
        self.DEVICES = 'USB123 offline\n'
        with self.assertRaisesRegex(DeviceError, 'USB'):
            self.client.enable_wireless()
        self.assertFalse(any('tcpip' in command for command, _ in self.commands))
        self.commands.clear()
        for port in [0, 65536, True, '5555']:
            with self.subTest(port=port), self.assertRaises(DeviceError):
                self.client.enable_wireless(port)
        self.assertFalse(self.commands)

    def test_enable_wireless_zero_exit_failure_is_reported_and_cache_cleared(self):
        self.client.select_device('USB123')
        self.client.screenshot()
        def fail_tcpip(command, **options):
            if 'tcpip' in command:
                return subprocess.CompletedProcess(command, 0, 'error: device offline', '')
            return self.run_adb(command, **options)
        self.mock_run.side_effect = fail_tcpip
        with self.assertRaisesRegex(DeviceError, 'device offline'):
            self.client.enable_wireless()
        self.assertIsNone(self.client._resolution)
        self.assertEqual('USB123', self.client.selected_serial)

    def test_disconnect_is_explicit_wireless_and_selected_failure_never_falls_back(self):
        self.client.select_device('10.0.35.91:5555')
        self.client.screenshot()
        for serial in ['', 'USB123', 'missing:5555', '-a']:
            with self.subTest(serial=serial), self.assertRaises(DeviceError):
                self.client.disconnect_wireless(serial)
        self.client.disconnect_wireless('10.0.35.91:5555')
        self.assertEqual(['disconnect', '10.0.35.91:5555'], self.commands[-1][0])
        self.assertIsNone(self.client._resolution)
        self.mock_run.side_effect = lambda args, **kwargs: subprocess.CompletedProcess(args, 1, '', 'device offline')
        with self.assertRaisesRegex(DeviceError, 'device offline'):
            self.client.tap(1, 2)
        self.assertEqual(['-s', '10.0.35.91:5555'], self.mock_run.call_args.args[0][1:3])
        self.assertEqual('10.0.35.91:5555', self.client.selected_serial)

    def test_switch_waits_for_screenshot_and_clears_its_cached_dimensions(self):
        self.client.select_device('USB123')
        entered, release, selecting = Event(), Event(), Event()
        original_run = self.mock_run.side_effect
        def slow_run(command, **options):
            if 'screencap' in command:
                entered.set()
                self.assertTrue(release.wait(2))
            return original_run(command, **options)
        self.mock_run.side_effect = slow_run
        def select():
            selecting.set()
            self.client.select_device('10.0.35.91:5555')
        with ThreadPoolExecutor(max_workers=2) as pool:
            screenshot = pool.submit(self.client.screenshot)
            self.assertTrue(entered.wait(2))
            selection = pool.submit(select)
            self.assertTrue(selecting.wait(2))
            self.assertFalse(selection.done())
            release.set()
            screenshot.result(timeout=2)
            selection.result(timeout=2)
        self.assertIsNone(self.client._resolution)
        self.assertEqual('10.0.35.91:5555', self.client.selected_serial)
