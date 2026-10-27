from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Sequence

import cv2
import numpy as np


class DeviceError(RuntimeError):
    pass


class AdbClient:
    def __init__(self, project_root: Path) -> None:
        candidates = [project_root / "adb.exe"]
        bundled_root = getattr(sys, "_MEIPASS", None)
        if bundled_root:
            candidates.append(Path(bundled_root) / "adb.exe")
        bundled = next((candidate for candidate in candidates if candidate.exists()), None)
        self.executable = str(bundled.resolve()) if bundled is not None else (
            shutil.which("adb") or "adb"
        )

    def _run(
        self,
        args: Sequence[str],
        *,
        timeout: float = 10,
        binary: bool = False,
    ) -> subprocess.CompletedProcess:
        options: dict[str, object] = {
            "capture_output": True,
            "timeout": timeout,
            "check": False,
        }
        if not binary:
            options.update({"text": True, "encoding": "utf-8", "errors": "replace"})
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            return subprocess.run([self.executable, *args], **options)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DeviceError(f"ADB 命令失败: {exc}") from exc

    @staticmethod
    def _error_text(result: subprocess.CompletedProcess) -> str:
        stderr = result.stderr
        if isinstance(stderr, bytes):
            return stderr.decode("utf-8", errors="replace").strip()
        return str(stderr or "").strip()

    def state(self) -> str:
        result = self._run(["get-state"])
        if result.returncode != 0:
            detail = self._error_text(result) or "未检测到设备"
            raise DeviceError(detail)
        return str(result.stdout).strip()

    def screenshot(self) -> np.ndarray:
        result = self._run(["exec-out", "screencap", "-p"], binary=True)
        if result.returncode != 0:
            raise DeviceError(self._error_text(result) or "截图失败")
        image_data = np.frombuffer(result.stdout, dtype=np.uint8)
        image = cv2.imdecode(image_data, cv2.IMREAD_COLOR)
        if image is None:
            raise DeviceError("无法解码设备截图")
        return image

    def screen_resolution(self) -> tuple[int, int]:
        image = self.screenshot()
        height, width = image.shape[:2]
        return int(width), int(height)

    def tap(self, x: int, y: int) -> None:
        result = self._run(["shell", "input", "tap", str(x), str(y)])
        if result.returncode != 0:
            raise DeviceError(self._error_text(result) or "点击失败")

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration: int = 300,
    ) -> None:
        result = self._run(
            [
                "shell",
                "input",
                "swipe",
                str(x1),
                str(y1),
                str(x2),
                str(y2),
                str(duration),
            ]
        )
        if result.returncode != 0:
            raise DeviceError(self._error_text(result) or "滑动失败")
