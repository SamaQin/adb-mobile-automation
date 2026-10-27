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
from model_automation.models import AppConfig, Preset, Step
from web_server import create_app


class FakeDevice:
    def __init__(self) -> None:
        y, x = np.indices((60, 100))
        self.screen = np.dstack((x, y, (x + y) % 255)).astype(np.uint8)

    def state(self) -> str:
        return "device"

    def screenshot(self) -> np.ndarray:
        return self.screen.copy()

    def screen_resolution(self) -> tuple[int, int]:
        return 100, 60

    def tap(self, _x: int, _y: int) -> None:
        pass

    def swipe(self, _x1: int, _y1: int, _x2: int, _y2: int, _duration: int) -> None:
        pass


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

        with self.client.websocket_connect("/ws/events") as websocket:
            replay = [websocket.receive_json() for _event in events]
        self.assertEqual(events, replay)

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


if __name__ == "__main__":
    unittest.main()
