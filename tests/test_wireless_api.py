from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from model_automation.config import ConfigStore
from model_automation.device import DeviceError
from web_server.app import create_app
from web_server.runtime import RuntimeConflict


class WirelessDevice:
    def __init__(self):
        self.selected_serial = 'usb-test'
        self.calls = []

    def state(self):
        return 'device'

    def screen_resolution(self):
        return 720, 1280

    def list_devices(self):
        return [{'serial': 'usb-test', 'state': 'device', 'model': 'Test', 'transport': 'usb'},
                {'serial': '10.0.35.91:5555', 'state': 'device', 'model': 'Phone', 'transport': 'wireless'}]

    def connect_wireless(self, host, port):
        self.calls.append(('connect', host, port))
        self.selected_serial = f'{host}:{port}'
        return {'message': '已连接无线设备', 'serial': self.selected_serial}

    def pair_wireless(self, host, port, code):
        self.calls.append(('pair', host, port, code))
        return {'message': '配对成功，请填写连接端口连接'}

    def select_device(self, serial):
        self.calls.append(('select', serial))
        self.selected_serial = serial

    def disconnect_wireless(self, serial):
        self.calls.append(('disconnect', serial))
        return {'message': '无线连接已断开', 'serial': serial}

    def enable_wireless(self, port):
        self.calls.append(('tcpip', port))
        return {'message': '已启用 TCP/IP', 'port': port, 'serial': self.selected_serial}


class WirelessApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        root = Path(self.temporary.name)
        self.device = WirelessDevice()
        self.stream = Mock()
        self.app = create_app(config_store=ConfigStore(root / 'config.json', root / 'templates'),
                              device=self.device, screencast=self.stream, static_dir=root / 'dist')
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.temporary.cleanup()

    def test_catalog_connect_select_and_target_metadata(self):
        result = self.client.get('/api/device/devices').json()
        self.assertEqual(result['selected_serial'], 'usb-test')
        response = self.client.post('/api/device/connect', json={'host': '10.0.35.91', 'port': 5555})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['device']['connected'])
        self.assertEqual(data['device']['transport'], 'wireless')
        self.assertEqual(data['device']['serial'], '10.0.35.91:5555')
        self.stream.set_device.assert_called_with('10.0.35.91:5555')
        response = self.client.post('/api/device/select', json={'serial': 'usb-test'})
        self.assertEqual(response.json()['device']['transport'], 'usb')
        self.stream.set_device.assert_called_with('usb-test')
        state = self.client.get('/api/device/state').json()['device']
        self.assertEqual(state['selected_serial'], 'usb-test')

    def test_pair_does_not_switch_stream_and_never_echoes_code(self):
        response = self.client.post('/api/device/pair', json={'host': '10.0.35.91', 'port': 37001, 'code': '123456'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['selected_serial'], 'usb-test')
        self.assertNotIn('123456', response.text)
        self.stream.set_device.assert_not_called()

    def test_mutations_rejected_during_run_before_device_or_stream_changes(self):
        runtime = self.app.state.runtime
        with patch.object(runtime, 'ensure_mutable', side_effect=RuntimeConflict('请先停止当前预设')):
            for endpoint, payload in [('connect', {'host': '10.0.35.91', 'port': 5555}),
                                      ('pair', {'host': '10.0.35.91', 'port': 37001, 'code': '123456'}),
                                      ('select', {'serial': 'usb-test'}), ('disconnect', {'serial': '10.0.35.91:5555'}),
                                      ('tcpip', {'port': 5555})]:
                with self.subTest(endpoint=endpoint):
                    response = self.client.post(f'/api/device/{endpoint}', json=payload)
                    self.assertEqual(response.status_code, 409)
        self.assertEqual(self.device.calls, [])
        self.stream.close.assert_not_called()
        self.stream.set_device.assert_not_called()

    def test_tcpip_closes_stream_and_disconnect_targets_only_serial(self):
        response = self.client.post('/api/device/tcpip', json={'port': 5555})
        self.assertEqual(response.status_code, 200)
        self.stream.close.assert_called_once()
        self.assertIn(('tcpip', 5555), self.device.calls)
        response = self.client.post('/api/device/disconnect', json={'serial': '10.0.35.91:5555'})
        self.assertEqual(response.status_code, 200)
        self.assertIn(('disconnect', '10.0.35.91:5555'), self.device.calls)

    def test_connect_failure_preserves_target_and_does_not_close_stream(self):
        with patch.object(self.device, 'connect_wireless', side_effect=DeviceError('连接被拒绝')):
            response = self.client.post('/api/device/connect', json={'host': '10.0.35.91', 'port': 5555})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.device.selected_serial, 'usb-test')
        self.stream.set_device.assert_not_called()


if __name__ == '__main__':
    unittest.main()
