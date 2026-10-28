from __future__ import annotations

import ipaddress
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from threading import RLock
import time
from typing import Sequence

import cv2
import numpy as np

from .adb_runtime import prepare_adb_environment


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
        self._environment = prepare_adb_environment(project_root)
        # One reentrant lock covers command dispatch, selection and dimension updates.
        self._lock = RLock()
        self._resolution_lock = self._lock
        self._selected_serial: str | None = None
        self._resolution: tuple[int, int] | None = None
        self._resolution_at = 0.0

    @property
    def selected_serial(self) -> str | None:
        with self._lock:
            return self._selected_serial

    @property
    def environment(self) -> dict[str, str]:
        return self._environment.copy()

    def _run(
        self,
        args: Sequence[str],
        *,
        timeout: float = 10,
        binary: bool = False,
        input_text: str | None = None,
        serial: str | None = None,
    ) -> subprocess.CompletedProcess:
        options: dict[str, object] = {
            "capture_output": True,
            "timeout": timeout,
            "check": False,
            "env": self._environment,
        }
        if not binary:
            options.update({"text": True, "encoding": "utf-8", "errors": "replace"})
        if input_text is not None:
            options["input"] = input_text
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        with self._lock:
            target = []
            target_serial = serial if serial is not None else self._selected_serial
            if args[0] not in {"devices", "connect", "pair", "disconnect"} and target_serial is not None:
                target = ["-s", target_serial]
            try:
                return subprocess.run([self.executable, *target, *args], **options)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise DeviceError(f"ADB 命令失败: {exc}") from exc

    @staticmethod
    def _validate_input_serial(serial: str | None) -> None:
        if serial is None:
            return
        if not isinstance(serial, str) or not serial.strip() or serial.startswith("-"):
            raise DeviceError("设备序列号无效")

    @staticmethod
    def _text(value: str | bytes | None) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace").strip()
        return str(value or "").strip()

    @classmethod
    def _error_text(cls, result: subprocess.CompletedProcess) -> str:
        return cls._text(result.stderr) or cls._text(result.stdout)

    @classmethod
    def _command_message(cls, result: subprocess.CompletedProcess, action: str) -> str:
        message = "\n".join(text for text in (cls._text(result.stdout), cls._text(result.stderr)) if text)
        # Some adb versions report connection/pairing failures with exit status 0.
        failed = re.search(r"\b(failed|failure|unable|error|cannot|refused)\b|can't|not connected|no such", message, re.I)
        if result.returncode != 0 or failed:
            raise DeviceError(f"{action}失败：{message or 'ADB 未返回错误详情'}")
        return message

    @staticmethod
    def _endpoint(host: str, port: int) -> str:
        if not isinstance(host, str) or not host or "%" in host:
            raise DeviceError("无线 ADB 地址必须是合法的 IPv4 或 IPv6 地址")
        literal = host[1:-1] if host.startswith("[") and host.endswith("]") else host
        try:
            address = ipaddress.ip_address(literal)
        except ValueError:
            raise DeviceError("无线 ADB 地址必须是合法的 IPv4 或 IPv6 地址") from None
        if type(port) is not int or not 1 <= port <= 65535:
            raise DeviceError("无线 ADB 端口必须是 1 到 65535 的整数")
        return f"[{address}]:{port}" if address.version == 6 else f"{address}:{port}"

    @staticmethod
    def _transport(serial: str) -> str:
        if serial.endswith("._adb-tls-connect._tcp") or serial.endswith("._adb-tls-connect._tcp."):
            return "wireless"
        host, separator, port = serial.rpartition(":")
        if separator and port.isascii() and port.isdigit():
            try:
                ipaddress.ip_address(host.strip("[]"))
                return "wireless"
            except ValueError:
                pass
        return "usb"

    def list_devices(self) -> list[dict[str, str]]:
        with self._lock:
            result = self._run(["devices", "-l"])
            if result.returncode != 0:
                raise DeviceError(f"读取 ADB 设备失败：{self._error_text(result) or '未返回设备列表'}")
            devices = []
            for line in self._text(result.stdout).splitlines():
                parts = line.split()
                if len(parts) < 2 or line.startswith(("List of devices", "*")):
                    continue
                serial, state = parts[:2]
                model = next((part.removeprefix("model:") for part in parts[2:] if part.startswith("model:")), "")
                devices.append({"serial": serial, "state": state, "model": model, "transport": self._transport(serial)})
            return devices

    def select_device(self, serial: str) -> None:
        with self._lock:
            if not isinstance(serial, str) or not any(
                device["serial"] == serial and device["state"] == "device" for device in self.list_devices()
            ):
                raise DeviceError("只能选择设备列表中状态为 device 的可用设备")
            if serial != self._selected_serial:
                self._selected_serial = serial
                self._clear_resolution()

    def connect_wireless(self, host: str, port: int) -> dict[str, str]:
        endpoint = self._endpoint(host, port)
        with self._lock:
            self._clear_resolution()
            message = self._command_message(self._run(["connect", endpoint], timeout=15), "无线 ADB 连接")
            devices = self.list_devices()
            # Compare IP endpoints canonically, since adb may expand an IPv6 address.
            serial = next((device["serial"] for device in devices
                           if device["state"] == "device" and self._same_endpoint(device["serial"], endpoint)), None)
            if serial is None:
                raise DeviceError(f"无线 ADB 连接未就绪：{message or endpoint}；设备列表中未发现状态为 device 的目标")
            self._selected_serial = serial
            self._clear_resolution()
            return {"endpoint": endpoint, "message": message or f"已连接 {endpoint}", "serial": serial}

    @staticmethod
    def _same_endpoint(serial: str, endpoint: str) -> bool:
        def canonical(value: str) -> tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, int]:
            host, _, port = value.rpartition(":")
            return ipaddress.ip_address(host.strip("[]")), int(port)
        try:
            return canonical(serial) == canonical(endpoint)
        except ValueError:
            return False

    def pair_wireless(self, host: str, port: int, code: str) -> dict[str, str]:
        endpoint = self._endpoint(host, port)
        if not isinstance(code, str) or re.fullmatch(r"[0-9]{6}", code) is None:
            raise DeviceError("无线 ADB 配对码必须是 6 位数字字符串")
        with self._lock:
            try:
                # adb pair HOST[:PORT] reads its interactive code from stdin.
                result = self._run(["pair", endpoint], timeout=20, input_text=code + "\n")
                usage = self._text(result.stdout) + "\n" + self._text(result.stderr)
                if re.search(r"\bpair\s+<?host>?\s+<?port>?\b", usage, re.I):
                    # A few adb distributions expose pair HOST PORT instead.
                    # Retry only an explicit usage response, never auth failures.
                    literal = endpoint.rpartition(":")[0].strip("[]")
                    result = self._run(["pair", literal, str(port)], timeout=20, input_text=code + "\n")
                # Sanitize before constructing any public error or response.
                safe_result = subprocess.CompletedProcess(result.args, result.returncode,
                    self._text(result.stdout).replace(code, "[已隐藏]"),
                    self._text(result.stderr).replace(code, "[已隐藏]"))
                message = self._command_message(safe_result, "无线 ADB 配对")
            except DeviceError as exc:
                raise DeviceError(str(exc).replace(code, "[已隐藏]")) from None
            return {"endpoint": endpoint, "message": message or "配对完成，请使用设备的连接端口连接"}

    def enable_wireless(self, port: int = 5555) -> dict[str, str | int]:
        """Enable legacy TCP/IP only on one authorized USB target; never connect."""
        if type(port) is not int or not 1 <= port <= 65535:
            raise DeviceError("无线 ADB 端口必须是 1 到 65535 的整数")
        with self._lock:
            devices = self.list_devices()
            if self._selected_serial is not None:
                target = next((device for device in devices if device["serial"] == self._selected_serial), None)
            else:
                available = [device for device in devices if device["state"] == "device"]
                target = available[0] if len(available) == 1 else None
            if target is None or target["state"] != "device" or target["transport"] != "usb":
                raise DeviceError("请先选择一台已授权且可用的 USB 设备，再启用无线 ADB")
            # Pin the USB target even in legacy automatic selection mode. tcpip
            # restarts adbd, and subsequent commands must never fall back elsewhere.
            self._selected_serial = target["serial"]
            self._clear_resolution()
            message = self._command_message(self._run(["tcpip", str(port)], timeout=15), "启用无线 ADB")
            return {"message": message or f"已启用端口 {port}，请连接设备的局域网 IP", "port": port, "serial": target["serial"]}

    def disconnect_wireless(self, serial: str) -> dict[str, str]:
        with self._lock:
            if not isinstance(serial, str) or not serial or serial.startswith("-") or not any(
                device["serial"] == serial and device["transport"] == "wireless" for device in self.list_devices()
            ):
                raise DeviceError("只能断开设备列表中指定的无线 ADB 设备")
            try:
                message = self._command_message(self._run(["disconnect", serial], timeout=10), "无线 ADB 断开")
            finally:
                self._clear_resolution()
            # Keep an explicitly selected target, even after disconnect. Falling back
            # to adb's default here could send the next input to an unrelated USB device.
            return {"serial": serial, "message": message or f"已断开 {serial}"}

    def _clear_resolution(self) -> None:
        with self._lock:
            self._resolution = None
            self._resolution_at = 0.0

    def state(self) -> str:
        with self._lock:
            try:
                result = self._run(["get-state"])
                if result.returncode != 0:
                    raise DeviceError(f"读取设备状态失败：{self._error_text(result) or '未检测到设备'}")
                state = self._text(result.stdout)
            except DeviceError:
                self._clear_resolution()
                raise
            if state != "device":
                self._clear_resolution()
            return state

    def screenshot(self) -> np.ndarray:
        with self._lock:
            try:
                result = self._run(["exec-out", "screencap", "-p"], binary=True)
                if result.returncode != 0:
                    raise DeviceError(f"截图失败：{self._error_text(result) or '未返回截图'}")
                image_data = np.frombuffer(result.stdout, dtype=np.uint8)
                if image_data.size == 0:
                    raise DeviceError("设备截图为空")
                image = cv2.imdecode(image_data, cv2.IMREAD_COLOR)
                if image is None:
                    raise DeviceError("无法解码设备截图")
            except (DeviceError, cv2.error) as exc:
                self._clear_resolution()
                if isinstance(exc, DeviceError):
                    raise
                raise DeviceError("无法解码设备截图") from exc
            height, width = image.shape[:2]
            self._resolution = int(width), int(height)
            self._resolution_at = time.monotonic()
            return image

    def screen_resolution(self, *, refresh: bool = False) -> tuple[int, int]:
        # Only reuse dimensions for a short burst of health checks; recognition
        # always captures a fresh image. Import can explicitly refresh after rotation.
        with self._lock:
            if not refresh and self._resolution is not None and time.monotonic() - self._resolution_at < 0.5:
                return self._resolution
            image = self.screenshot()
            height, width = image.shape[:2]
            return int(width), int(height)

    def tap(self, x: int, y: int) -> None:
        self.tap_on(None, x, y)

    def tap_on(self, serial: str | None, x: int, y: int) -> None:
        self._validate_input_serial(serial)
        with self._lock:
            try:
                result = self._run(
                    ["shell", "input", "tap", str(x), str(y)], serial=serial
                )
                if result.returncode != 0:
                    raise DeviceError(f"点击失败：{self._error_text(result) or 'ADB 未返回错误详情'}")
            except DeviceError:
                self._clear_resolution()
                raise

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> None:
        self.swipe_on(None, x1, y1, x2, y2, duration)

    def swipe_on(
        self, serial: str | None, x1: int, y1: int, x2: int, y2: int,
        duration: int = 300,
    ) -> None:
        self._validate_input_serial(serial)
        with self._lock:
            try:
                result = self._run(
                    ["shell", "input", "swipe", str(x1), str(y1), str(x2),
                     str(y2), str(duration)],
                    serial=serial,
                )
                if result.returncode != 0:
                    raise DeviceError(f"滑动失败：{self._error_text(result) or 'ADB 未返回错误详情'}")
            except DeviceError:
                self._clear_resolution()
                raise
