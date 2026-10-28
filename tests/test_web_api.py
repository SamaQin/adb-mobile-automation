import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch
from pathlib import Path
from queue import Queue
from tempfile import TemporaryDirectory
import time
import unittest
import warnings

import cv2
import numpy as np

warnings.filterwarnings(
    "ignore", message="Using `httpx` with `starlette.testclient` is deprecated"
)

from fastapi.testclient import TestClient

from model_automation.config import ConfigStore
from model_automation.device import DeviceError
from model_automation.models import AppConfig, Preset, Step
from web_server import create_app


class FakeDevice:
    def __init__(self) -> None:
        y, x = np.indices((60, 100))
        self.screen = np.dstack((x, y, (x + y) % 255)).astype(np.uint8)
        self.inputs: list[tuple] = []

    def state(self) -> str:
        return "device"

    def screenshot(self) -> np.ndarray:
        return self.screen.copy()

    def screen_resolution(self) -> tuple[int, int]:
        return 100, 60

    def tap(self, x: int, y: int) -> None:
        self.inputs.append(("tap", None, x, y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int) -> None:
        self.inputs.append(("swipe", None, x1, y1, x2, y2, duration))

    def tap_on(self, serial: str, x: int, y: int) -> None:
        self.inputs.append(("tap", serial, x, y))

    def swipe_on(self, serial: str, x1: int, y1: int, x2: int, y2: int,
                 duration: int) -> None:
        self.inputs.append(("swipe", serial, x1, y1, x2, y2, duration))


def png_bytes(image: np.ndarray) -> bytes:
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise RuntimeError("test image encoding failed")
    return encoded.tobytes()


class FakeSubscriber:
    def __init__(self, frames: list[bytes | None]) -> None:
        self.frames = Queue()
        for frame in frames:
            self.frames.put(frame)


class FakeScreencast:
    def __init__(self) -> None:
        self.subscriber = FakeSubscriber([b"first", b"second", None])
        self.touched = 0
        self.closed = False

    def subscribe(self) -> FakeSubscriber:
        return self.subscriber

    def touch(self, _subscriber: FakeSubscriber) -> None:
        self.touched += 1

    def unsubscribe(self, _subscriber: FakeSubscriber) -> None:
        pass

    def status(self) -> dict[str, object]:
        return {"state": "streaming", "message": "", "fps": 30, "subscribers": 1}

    def close(self) -> None:
        self.closed = True


class WebApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        root = Path(self.temporary.name)
        self.store = ConfigStore(root / "config.json", root / "templates")
        self.device = FakeDevice()
        self.client = TestClient(
            create_app(config_store=self.store, device=self.device, static_dir=root / "dist")
        )

    def tearDown(self) -> None:
        self.client.close()
        self.temporary.cleanup()

    def save(self, presets: list[Preset], selected: Preset | None = None) -> None:
        selected = selected or presets[0]
        self.store.save(AppConfig(presets=presets, selected_preset_id=selected.id))

    def test_health_config_definitions_and_recursive_validation(self) -> None:
        config = self.store.load()
        self.assertEqual({"status": "ok"}, self.client.get("/api/health").json())
        self.assertEqual(200, self.client.get("/api/config").status_code)
        device = self.client.get("/api/device/state").json()
        self.assertTrue(device["device"]["connected"])

        definitions = self.client.get("/api/step-definitions").json()
        self.assertIn("recorded_actions", {item["key"] for item in definitions})
        find_definition = next(item for item in definitions if item["key"] == "find_and_tap")
        self.assertTrue(find_definition["can_fail"])
        self.assertTrue(any(field["kind"] == "templates" for field in find_definition["fields"]))

        invalid = config.to_dict()
        invalid["presets"][0]["loop_count"] = -1
        response = self.client.put("/api/config", json=invalid)
        self.assertEqual(400, response.status_code)
        self.assertIsInstance(response.json()["detail"], str)

        acceleration = self.client.put(
            "/api/settings/acceleration", json={"acceleration": "cpu"}
        )
        self.assertEqual("cpu", acceleration.json()["acceleration"])

    def test_device_state_keeps_transport_connected_when_screenshot_fails(self) -> None:
        with patch.object(self.device, "screen_resolution", side_effect=DeviceError("截图失败：设备截图为空")):
            response = self.client.get("/api/device/state")

        self.assertEqual(200, response.status_code)
        device = response.json()["device"]
        self.assertTrue(device["connected"])
        self.assertEqual("device", device["state"])
        self.assertIsNone(device["resolution"])
        self.assertEqual("截图失败：设备截图为空", device["error"])

    def test_device_input_tap_and_swipe_with_optional_serial(self) -> None:
        tap = self.client.post(
            "/api/device/input",
            json={"type": "tap", "x": 10, "y": 20, "serial": "USB123"},
        )
        self.assertEqual(200, tap.status_code, tap.text)
        swipe = self.client.post(
            "/api/device/input",
            json={"type": "swipe", "x1": 1, "y1": 2, "x2": 3, "y2": 4,
                  "duration": 300, "serial": "USB123"},
        )
        self.assertEqual(200, swipe.status_code, swipe.text)
        self.assertEqual([
            ("tap", "USB123", 10, 20),
            ("swipe", "USB123", 1, 2, 3, 4, 300),
        ], self.device.inputs)

    def test_device_input_rejects_invalid_payload(self) -> None:
        invalid = [
            {},
            {"type": "tap", "x": True, "y": 1},
            {"type": "tap", "x": -1, "y": 1},
            {"type": "swipe", "x1": 0, "y1": 0, "x2": 1, "y2": 1, "duration": 0},
            {"type": "swipe", "x1": 0, "y1": 0, "x2": 1, "y2": 1, "duration": 5001},
            {"type": "tap", "x": 1, "y": 1, "serial": "-a"},
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                response = self.client.post("/api/device/input", json=payload)
                self.assertEqual(400, response.status_code, response.text)
        self.assertEqual([], self.device.inputs)

    def test_device_input_is_rejected_while_a_preset_runs(self) -> None:
        preset = Preset(name="running", steps=[Step(name="wait", kind="wait", params={"seconds": 5})])
        self.save([preset])
        self.assertEqual(200, self.client.post("/api/run", json={"preset_id": preset.id}).status_code)
        response = self.client.post("/api/device/input", json={"type": "tap", "x": 1, "y": 2})
        self.assertEqual(409, response.status_code)
        self.assertEqual([], self.device.inputs)
        self.assertEqual(200, self.client.post("/api/stop").status_code)

    def test_duplicate_and_reference_scan_include_nested_steps(self) -> None:
        target = Preset(name="target")
        nested = Step(
            name="nested run",
            kind="run_preset",
            params={"preset_id": target.id, "preset_name": target.name},
        )
        root = Step(
            name="recognize",
            kind="find_and_tap",
            params={
                "templates": [{"file": "target.png", "threshold": 0.8}],
                "branches": {"0": [nested.to_dict()]},
            },
            screen_resolution=(100, 60),
        )
        source = Preset(name="source", steps=[root])
        self.save([source, target], source)

        response = self.client.post(f"/api/presets/{source.id}/duplicate", json={})

        self.assertEqual(200, response.status_code, response.text)
        duplicate = response.json()["preset"]
        duplicate_nested = duplicate["steps"][0]["params"]["branches"]["0"][0]
        self.assertNotEqual(root.id, duplicate["steps"][0]["id"])
        self.assertNotEqual(nested.id, duplicate_nested["id"])
        references = self.client.get(
            f"/api/presets/{target.id}/references"
        ).json()["references"]
        self.assertEqual({"source", "source 副本"}, {item["preset_name"] for item in references})

    def test_screenshot_template_upload_capture_recapture_and_delete(self) -> None:
        reference = Step(
            name="recognize",
            kind="find_and_tap",
            params={"templates": [{"file": "target.png", "threshold": 0.8}]},
            screen_resolution=(50, 30),
        )
        preset = Preset(name="preset", steps=[reference])
        self.save([preset])

        screenshot = self.client.get("/api/device/screenshot?max_width=50")
        self.assertEqual("image/png", screenshot.headers["content-type"])
        self.assertEqual("no-store", screenshot.headers["cache-control"])
        decoded = cv2.imdecode(np.frombuffer(screenshot.content, np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual((30, 50), decoded.shape[:2])

        live_frame = self.client.get(
            "/api/device/screenshot?max_width=25&format=jpeg"
        )
        self.assertEqual("image/jpeg", live_frame.headers["content-type"])
        self.assertEqual("no-store", live_frame.headers["cache-control"])
        live_decoded = cv2.imdecode(
            np.frombuffer(live_frame.content, np.uint8), cv2.IMREAD_COLOR
        )
        self.assertEqual((15, 25), live_decoded.shape[:2])

        image = np.full((8, 12, 3), 90, dtype=np.uint8)
        uploaded = self.client.post(
            "/api/templates/upload",
            files={"file": ("target.png", png_bytes(image), "image/png")},
        )
        self.assertEqual(200, uploaded.status_code, uploaded.text)
        self.assertEqual((12, 8), (uploaded.json()["width"], uploaded.json()["height"]))
        self.assertEqual(1, len(uploaded.json()["references"]))

        captured = self.client.post(
            "/api/templates/capture",
            json={
                "name": "clipped",
                "rect": {"x": -2, "y": -3, "width": 5, "height": 6},
                "threshold": 0.9,
            },
        )
        self.assertEqual(200, captured.status_code, captured.text)
        self.assertEqual((3, 3), (captured.json()["width"], captured.json()["height"]))

        recaptured = self.client.post(
            "/api/templates/target.png/recapture",
            json={
                "rect": {"x": 10, "y": 10, "width": 20, "height": 15},
                "threshold": 0.7,
            },
        )
        self.assertEqual(1, recaptured.json()["updated_references"])
        updated_reference = self.store.load().presets[0].steps[0].params["templates"][0]
        self.assertEqual(
            {"width": 100, "height": 60}, updated_reference["screen_resolution"]
        )
        self.assertEqual(2, len(self.client.get("/api/templates").json()))
        self.assertEqual(
            200, self.client.get("/api/templates/target.png/thumbnail").status_code
        )
        self.assertEqual(
            200, self.client.delete("/api/templates/target.png").status_code
        )

    def test_stream_endpoints_report_unavailable_for_injected_devices(self) -> None:
        status = self.client.get("/api/device/stream/status")
        self.assertEqual(200, status.status_code)
        self.assertEqual("unavailable", status.json()["state"])

        stream = self.client.get("/api/device/stream")
        self.assertEqual(503, stream.status_code)
        self.assertEqual("当前设备不支持实时投屏", stream.json()["detail"])

    def test_stream_endpoint_emits_length_prefixed_jpeg_frames(self) -> None:
        fake = FakeScreencast()
        with TestClient(
            create_app(
                config_store=self.store,
                device=self.device,
                screencast=fake,
            )
        ) as client:
            response = client.get("/api/device/stream")

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            b"\x00\x00\x00\x05first\x00\x00\x00\x06second",
            response.content,
        )
        self.assertEqual("application/octet-stream", response.headers["content-type"])
        self.assertEqual("jpeg-length-prefixed", response.headers["x-stream-format"])
        self.assertGreaterEqual(fake.touched, 2)
        self.assertTrue(fake.closed)

    def test_coordinate_scaling_and_archive_roundtrip(self) -> None:
        step = Step(
            name="tap",
            kind="tap",
            params={"x": 25, "y": 20},
            screen_resolution=(50, 40),
        )
        preset = Preset(name="archive", steps=[step])
        self.save([preset])

        scaled = self.client.post(
            "/api/coords/scale",
            json={
                "step": step.to_dict(),
                "target_resolution": {"width": 100, "height": 80},
            },
        )
        self.assertEqual({"x": 50, "y": 40}, scaled.json()["params"])
        self.assertEqual({"x": 25, "y": 20}, step.params)

        exported = self.client.get(f"/api/archive/export?preset_id={preset.id}")
        self.assertEqual(200, exported.status_code, exported.text)
        imported = self.client.post(
            "/api/archive/import",
            files={"file": ("archive.zip", exported.content, "application/zip")},
        )
        self.assertEqual(200, imported.status_code, imported.text)
        self.assertEqual("archive 导入", imported.json()["preset"]["name"])
        self.assertEqual(2, len(self.store.load().presets))

    def test_run_lock_stop_and_websocket_replay(self) -> None:
        preset = Preset(
            name="running",
            steps=[Step(name="wait", kind="wait", params={"seconds": 5})],
        )
        self.save([preset])

        started = self.client.post("/api/run", json={"preset_id": preset.id})
        self.assertEqual("running", started.json()["state"])
        conflict = self.client.put("/api/config", json=self.store.load().to_dict())
        self.assertEqual(409, conflict.status_code)
        self.assertEqual(200, self.client.post("/api/stop").status_code)

        deadline = time.monotonic() + 2
        while self.client.get("/api/run/status").json()["state"] != "idle":
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        events = self.client.app.state.runtime.events()
        self.assertEqual("finished", events[-1]["type"])
        self.assertEqual("stopped", events[-1]["data"]["status"])
        self.assertTrue(
            any(event["type"] == "step" and event["data"]["state"] == "running" for event in events)
        )

        display_events = [event for event in events if event["type"] in {"log", "device"}]
        with self.client.websocket_connect("/ws/events") as websocket:
            replay = [websocket.receive_json() for _event in display_events]
            snapshot = websocket.receive_json()
        self.assertEqual(display_events, replay)
        self.assertEqual("status", snapshot["type"])
        self.assertEqual("idle", snapshot["data"]["state"])
        self.assertEqual("stopped", snapshot["data"]["last_status"])
        self.assertIn("node_states", snapshot["data"])
        self.assertEqual(events[-1]["seq"], snapshot["seq"])

    def test_run_accepts_start_step_and_rejects_invalid_start(self) -> None:
        first = Step(name="first", kind="wait", params={"seconds": 5})
        second = Step(name="second", kind="wait", params={"seconds": 0.01})
        preset = Preset(name="start", steps=[first, second])
        self.save([preset])

        started = self.client.post(
            "/api/run",
            json={"preset_id": preset.id, "start_step_id": second.id},
        )
        self.assertEqual(200, started.status_code, started.text)
        self.assertEqual("running", started.json()["state"])

        deadline = time.monotonic() + 2
        while self.client.get("/api/run/status").json()["state"] != "idle":
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)

        events = self.client.app.state.runtime.events()
        running_ids = {
            event["data"]["step_id"]
            for event in events
            if event["type"] == "step" and event["data"]["state"] == "running"
        }
        self.assertEqual({second.id}, running_ids)
        self.assertEqual("completed", self.client.get("/api/run/status").json()["last_status"])

        invalid = self.client.post(
            "/api/run",
            json={"preset_id": preset.id, "start_step_id": "missing"},
        )
        self.assertEqual(400, invalid.status_code)
        self.assertEqual("idle", self.client.get("/api/run/status").json()["state"])

    def test_template_list_indexes_references_once_and_thumbnails_revalidate(self) -> None:
        from model_automation.operations import template_reference_index
        preset = Preset(name="templates", steps=[Step(name="recognize", kind="find_and_tap", params={
            "templates": [{"file": "a.png", "threshold": 0.8}, {"file": "b.png", "threshold": 0.8}]
        })])
        self.save([preset])
        self.store.template_dir.mkdir(parents=True, exist_ok=True)
        for name in ["a.png", "b.png"]:
            (self.store.template_dir / name).write_bytes(png_bytes(self.device.screen))
        with patch("web_server.app.template_reference_index", wraps=template_reference_index) as index:
            records = self.client.get("/api/templates").json()
            self.assertEqual(1, index.call_count)
        self.assertEqual(["a.png", "b.png"], [record["name"] for record in records])
        self.assertTrue(all(record["references"][0]["step_id"] == preset.steps[0].id for record in records))
        first = self.client.get("/api/templates/a.png/thumbnail?max_width=20")
        self.assertEqual(200, first.status_code)
        unchanged = self.client.get("/api/templates/a.png/thumbnail?max_width=20", headers={"If-None-Match": first.headers["etag"]})
        self.assertEqual(304, unchanged.status_code)
        (self.store.template_dir / "a.png").write_bytes(png_bytes(np.zeros((30, 40, 3), dtype=np.uint8)))
        changed = self.client.get("/api/templates/a.png/thumbnail?max_width=20", headers={"If-None-Match": first.headers["etag"]})
        self.assertEqual(200, changed.status_code)
        self.assertNotEqual(first.headers["etag"], changed.headers["etag"])
        self.assertNotEqual(records[0]["revision"], self.client.get("/api/templates").json()[0]["revision"])

    def test_h264_stream_forwards_encoded_packets_and_validates_codec(self) -> None:
        class H264Screencast(FakeScreencast):
            def subscribe_h264(self):
                self.subscriber = FakeSubscriber([b"encoded-session", b"encoded-packet", None])
                return self.subscriber
        screencast = H264Screencast()
        with TestClient(create_app(config_store=self.store, device=self.device, screencast=screencast)) as client:
            response = client.get("/api/device/stream?codec=h264")
            self.assertEqual(200, response.status_code)
            self.assertIn("application/x-adb-h264", response.headers["content-type"])
            self.assertEqual(b"encoded-sessionencoded-packet", response.content)
            self.assertEqual(400, client.get("/api/device/stream?codec=invalid").status_code)
        with TestClient(create_app(config_store=self.store, device=self.device, screencast=FakeScreencast())) as client:
            self.assertEqual(503, client.get("/api/device/stream?codec=h264").status_code)

    def test_static_files_use_spa_fallback(self) -> None:
        root = Path(self.temporary.name)
        dist = root / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<main>app</main>", encoding="utf-8")
        (dist / "asset.txt").write_text("asset", encoding="utf-8")
        with TestClient(
            create_app(config_store=self.store, device=self.device, static_dir=dist)
        ) as client:
            self.assertEqual("asset", client.get("/asset.txt").text)
            self.assertEqual("<main>app</main>", client.get("/nested/route").text)

    def test_upload_rechecks_mutability_after_body_wait(self) -> None:
        preset = Preset(name="running", steps=[Step(name="wait", kind="wait", params={"seconds": 5})])
        self.save([preset])
        entered, release = Event(), Event()
        async def delayed_upload(*_args):
            entered.set()
            await asyncio.to_thread(release.wait, 2)
            return "late.png", png_bytes(self.device.screen)
        with patch("web_server.app._uploaded_file", side_effect=delayed_upload):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.client.post, "/api/templates/upload", content=b"body")
                try:
                    self.assertTrue(entered.wait(1))
                    self.assertEqual(200, self.client.post("/api/run", json={"preset_id": preset.id}).status_code)
                    release.set()
                    self.assertEqual(409, future.result(timeout=2).status_code)
                    self.assertFalse((self.store.template_dir / "late.png").exists())
                finally:
                    release.set()
                    self.client.post("/api/stop")

    def test_idle_websocket_disconnect_unsubscribes_without_events(self) -> None:
        manager = self.client.app.state.runtime
        with self.client.websocket_connect("/ws/events"):
            pass
        self.assertEqual([], manager._subscribers)

    def test_concurrent_duplicates_do_not_lose_updates(self) -> None:
        preset = Preset(name="source")
        self.save([preset])
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: self.client.post(f"/api/presets/{preset.id}/duplicate", json={}), range(8)))
        self.assertTrue(all(response.status_code == 200 for response in responses))
        presets = self.store.load().presets
        self.assertEqual(9, len(presets))
        self.assertEqual(9, len({preset.name for preset in presets}))


if __name__ == "__main__":
    unittest.main()
