from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import logging
from pathlib import Path
import queue
import secrets
import socket
import subprocess
import time
from threading import Event, RLock, Thread, Timer, current_thread
from typing import Any

import av
import cv2

LOGGER = logging.getLogger(__name__)

SCRCPY_VERSION = "5.0.1"
SCRCPY_REMOTE_PATH = "/data/local/tmp/adb-automation-scrcpy-5.0.1.jar"
H264_CODEC_ID = 0x68323634
MAX_PACKET_SIZE = 16 * 1024 * 1024
STREAM_SESSION_FLAG = 1 << 63
PACKET_CONFIG_FLAG = 1 << 62
PACKET_KEY_FRAME_FLAG = 1 << 61
PACKET_PTS_MASK = (1 << 61) - 1
JPEG_QUALITY = 82


class ScreencastError(RuntimeError):
    pass


@dataclass(frozen=True)
class StreamSession:
    width: int
    height: int
    client_resize: bool = False


@dataclass(frozen=True)
class VideoPacket:
    pts: int
    size: int
    config: bool
    key_frame: bool


def parse_stream_header(header: bytes) -> StreamSession | VideoPacket:
    if len(header) != 12:
        raise ScreencastError("投屏数据头长度无效")
    values = int.from_bytes(header[:8], "big")
    if values & STREAM_SESSION_FLAG:
        width = int.from_bytes(header[4:8], "big")
        height = int.from_bytes(header[8:12], "big")
        if width <= 0 or height <= 0:
            raise ScreencastError("投屏分辨率无效")
        return StreamSession(
            width=width,
            height=height,
            client_resize=bool(values & 1),
        )
    size = int.from_bytes(header[8:12], "big")
    if size <= 0 or size > MAX_PACKET_SIZE:
        raise ScreencastError(f"投屏数据包大小无效：{size}")
    return VideoPacket(
        pts=values & PACKET_PTS_MASK,
        size=size,
        config=bool(values & PACKET_CONFIG_FLAG),
        key_frame=bool(values & PACKET_KEY_FRAME_FLAG),
    )


def avcc_to_annexb(data: bytes, length_size: int) -> bytes:
    if length_size not in {1, 2, 4}:
        raise ScreencastError(f"不支持的 H.264 NAL 长度：{length_size}")
    output = bytearray()
    offset = 0
    while offset + length_size <= len(data):
        size = int.from_bytes(data[offset:offset + length_size], "big")
        offset += length_size
        if size <= 0 or offset + size > len(data):
            raise ScreencastError("H.264 数据包不完整")
        output += b"\x00\x00\x00\x01"
        output += data[offset:offset + size]
        offset += size
    if offset != len(data) or not output:
        raise ScreencastError("H.264 数据包格式无效")
    return bytes(output)


def payload_to_annexb(data: bytes, length_size: int = 4) -> bytes:
    if data.startswith(b"\x00\x00\x00\x01") or data.startswith(b"\x00\x00\x01"):
        return data
    return avcc_to_annexb(data, length_size)


def config_to_annexb(data: bytes) -> tuple[bytes, int]:
    if data.startswith(b"\x00\x00\x00\x01") or data.startswith(b"\x00\x00\x01"):
        return data, 4
    if len(data) < 7 or data[0] != 1:
        raise ScreencastError("无法识别 H.264 配置数据")
    length_size = (data[4] & 0x03) + 1
    offset = 6
    output = bytearray()
    sps_count = data[5] & 0x1F
    for _ in range(sps_count):
        if offset + 2 > len(data):
            raise ScreencastError("H.264 SPS 配置不完整")
        size = int.from_bytes(data[offset:offset + 2], "big")
        offset += 2
        if size <= 0 or offset + size > len(data):
            raise ScreencastError("H.264 SPS 配置无效")
        output += b"\x00\x00\x00\x01" + data[offset:offset + size]
        offset += size
    if offset >= len(data):
        raise ScreencastError("H.264 PPS 配置缺失")
    pps_count = data[offset]
    offset += 1
    for _ in range(pps_count):
        if offset + 2 > len(data):
            raise ScreencastError("H.264 PPS 配置不完整")
        size = int.from_bytes(data[offset:offset + 2], "big")
        offset += 2
        if size <= 0 or offset + size > len(data):
            raise ScreencastError("H.264 PPS 配置无效")
        output += b"\x00\x00\x00\x01" + data[offset:offset + size]
        offset += size
    if not output:
        raise ScreencastError("H.264 配置数据为空")
    return bytes(output), length_size


def _recv_exact(connection: socket.socket, length: int) -> bytes:
    data = bytearray()
    while len(data) < length:
        chunk = connection.recv(length - len(data))
        if not chunk:
            raise ScreencastError("投屏连接已断开")
        data.extend(chunk)
    return bytes(data)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


@dataclass(eq=False)
class FrameSubscriber:
    identifier: int
    frames: queue.Queue[bytes | None]
    first_frame_at: float | None = None


class ScrcpyScreencast:
    """Share one low-latency scrcpy H.264 stream between browser clients."""

    def __init__(
        self,
        adb_executable: str | Path,
        server_path: str | Path,
        *,
        max_size: int = 720,
        max_fps: int = 30,
        video_bit_rate: int = 4_000_000,
        idle_timeout: float = 2.0,
    ) -> None:
        self.adb_executable = str(adb_executable)
        self.server_path = Path(server_path)
        self.max_size = int(max_size)
        self.max_fps = int(max_fps)
        self.video_bit_rate = int(video_bit_rate)
        self.idle_timeout = idle_timeout
        self._lock = RLock()
        self._subscribers: dict[int, FrameSubscriber] = {}
        self._next_subscriber = 1
        self._socket: socket.socket | None = None
        self._process: subprocess.Popen[str] | None = None
        self._port: int | None = None
        self._reader_thread: Thread | None = None
        self._idle_timer: Timer | None = None
        self._subscriber_guard: Timer | None = None
        self._closing = False
        self._cleanup_done = Event()
        self._cleanup_done.set()
        self._stop_requested = False
        self._state = "idle"
        self._message = ""
        self._width = 0
        self._height = 0
        self._fps = 0.0
        self._frame_times: deque[float] = deque()
        self._latest_jpeg: bytes | None = None
        self._device_name = ""
        self._log_lines: deque[str] = deque(maxlen=40)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state,
                "message": self._message,
                "codec": "h264",
                "width": self._width,
                "height": self._height,
                "fps": round(self._fps, 1),
                "subscribers": len(self._subscribers),
                "max_fps": self.max_fps,
                "device": self._device_name,
            }

    def subscribe(self) -> FrameSubscriber:
        while True:
            self._cleanup_done.wait(timeout=5)
            with self._lock:
                if self._closing:
                    continue
                self._cancel_idle_timer_locked()
                if self._reader_thread is None or not self._reader_thread.is_alive():
                    self._start_locked()
                subscriber = FrameSubscriber(
                    self._next_subscriber, queue.Queue(maxsize=1)
                )
                self._next_subscriber += 1
                self._subscribers[subscriber.identifier] = subscriber
                if self._latest_jpeg is not None:
                    self._offer(subscriber, self._latest_jpeg)
                self._schedule_subscriber_guard_locked()
                return subscriber

    def touch(self, subscriber: FrameSubscriber) -> None:
        with self._lock:
            current = self._subscribers.get(subscriber.identifier)
            if current is not None and current.first_frame_at is None:
                current.first_frame_at = time.monotonic()

    def unsubscribe(self, subscriber: FrameSubscriber) -> None:
        with self._lock:
            self._subscribers.pop(subscriber.identifier, None)
            should_stop = (
                not self._subscribers
                and self._reader_thread is not None
                and self._reader_thread.is_alive()
            )
            if should_stop:
                self._schedule_idle_stop_locked()
            else:
                self._cancel_idle_timer_locked()
            if not self._subscribers and self._subscriber_guard is not None:
                self._subscriber_guard.cancel()
                self._subscriber_guard = None

    def close(self) -> None:
        with self._lock:
            if self._closing:
                return
            self._closing = True
            self._cleanup_done.clear()
            self._cancel_idle_timer_locked()
            if self._subscriber_guard is not None:
                self._subscriber_guard.cancel()
                self._subscriber_guard = None
            self._stop_requested = True
            subscribers = list(self._subscribers.values())
            self._subscribers.clear()
            connection = self._socket
            process = self._process
            port = self._port
            reader = self._reader_thread
            self._socket = None
            self._process = None
            self._port = None
            self._reader_thread = None
            self._state = "idle"
            self._message = ""
            self._fps = 0.0
            self._frame_times.clear()
            self._latest_jpeg = None
        try:
            for subscriber in subscribers:
                self._offer(subscriber, None)
            self._release(connection, process, port, reader)
        finally:
            with self._lock:
                self._closing = False
                self._cleanup_done.set()

    def _start_locked(self) -> None:
        self._state = "starting"
        self._message = ""
        self._width = 0
        self._height = 0
        self._fps = 0.0
        self._frame_times.clear()
        self._latest_jpeg = None
        self._log_lines.clear()
        self._stop_requested = False
        connection: socket.socket | None = None
        process: subprocess.Popen[str] | None = None
        port: int | None = None
        try:
            self._push_server()
            port = _free_port()
            scid = secrets.randbelow(0x7FFFFFFF) + 1
            socket_name = f"scrcpy_{scid:08x}"
            self._run_adb("forward", f"tcp:{port}", f"localabstract:{socket_name}")
            self._port = port
            process = self._launch_server(scid)
            self._process = process
            connection = self._connect_ready(port, process)
            self._socket = connection
            self._read_handshake(connection)
            self._reader_thread = Thread(
                target=self._reader_loop,
                args=(connection,),
                name="scrcpy-video-reader",
                daemon=True,
            )
            self._state = "starting"
            self._message = "正在等待设备首帧"
            self._reader_thread.start()
        except Exception as exc:
            if isinstance(exc, ScreencastError):
                LOGGER.warning("Could not start scrcpy screencast: %s", exc)
            else:
                LOGGER.exception("Could not start scrcpy screencast")
            self._state = "error"
            self._message = str(exc) or "投屏服务启动失败"
            self._socket = None
            self._process = None
            self._port = None
            self._reader_thread = None
            self._release(connection, process, port, None, remove_forward=True)
            raise ScreencastError(self._message) from exc

    def _push_server(self) -> None:
        if not self.server_path.is_file():
            raise ScreencastError(
                "找不到 scrcpy 投屏服务文件，请重新安装完整版本"
            )
        self._run_adb("push", str(self.server_path), SCRCPY_REMOTE_PATH, timeout=30)

    def _launch_server(self, scid: int) -> subprocess.Popen[str]:
        arguments = [
            self.adb_executable,
            "shell",
            f"CLASSPATH={SCRCPY_REMOTE_PATH}",
            "app_process",
            "/",
            "com.genymobile.scrcpy.Server",
            SCRCPY_VERSION,
            f"scid={scid:08x}",
            "log_level=info",
            "audio=false",
            "control=false",
            "tunnel_forward=true",
            f"max_size={self.max_size}",
            f"max_fps={self.max_fps}",
            f"video_bit_rate={self.video_bit_rate}",
            "send_device_meta=true",
            "send_frame_meta=true",
            "send_stream_meta=true",
            "send_dummy_byte=true",
            "cleanup=true",
        ]
        try:
            process = subprocess.Popen(
                arguments,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=_creation_flags(),
            )
        except OSError as exc:
            raise ScreencastError(f"无法启动 scrcpy 服务：{exc}") from exc
        if process.stdout is not None:
            Thread(
                target=self._drain_server_output,
                args=(process.stdout,),
                name="scrcpy-server-output",
                daemon=True,
            ).start()
        return process

    def _drain_server_output(self, stream: Any) -> None:
        try:
            for line in stream:
                text = line.strip()
                if text:
                    self._log_lines.append(text)
        except (OSError, ValueError):
            pass

    def _connect_ready(
        self, port: int, process: subprocess.Popen[str]
    ) -> socket.socket:
        deadline = time.monotonic() + 15
        last_error = "连接超时"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise ScreencastError(self._startup_error("投屏服务提前退出"))
            candidate: socket.socket | None = None
            try:
                time.sleep(0.12)
                candidate = socket.create_connection(("127.0.0.1", port), timeout=1.5)
                candidate.settimeout(5)
                if _recv_exact(candidate, 1) == b"\x00":
                    candidate.settimeout(10)
                    return candidate
                raise ScreencastError("投屏服务握手无效")
            except (OSError, ScreencastError) as exc:
                last_error = str(exc) or "连接失败"
                if candidate is not None:
                    try:
                        candidate.close()
                    except OSError:
                        pass
        raise ScreencastError(self._startup_error(f"投屏服务未就绪：{last_error}"))

    def _read_handshake(self, connection: socket.socket) -> None:
        name = _recv_exact(connection, 64).split(b"\x00", 1)[0]
        self._device_name = name.decode("utf-8", errors="replace")
        codec_id = int.from_bytes(_recv_exact(connection, 4), "big")
        if codec_id != H264_CODEC_ID:
            raise ScreencastError("设备投屏编码不是 H.264，无法播放")
        meta = parse_stream_header(_recv_exact(connection, 12))
        if not isinstance(meta, StreamSession):
            raise ScreencastError("投屏流元数据无效")
        self._width = meta.width
        self._height = meta.height

    def _reader_loop(self, connection: socket.socket) -> None:
        decoder = self._new_decoder()
        length_size = 4
        try:
            while True:
                header = parse_stream_header(_recv_exact(connection, 12))
                if isinstance(header, StreamSession):
                    self._width = header.width
                    self._height = header.height
                    decoder = self._new_decoder()
                    length_size = 4
                    continue
                payload = _recv_exact(connection, header.size)
                if header.config:
                    annexb, length_size = config_to_annexb(payload)
                    self._decode(decoder, annexb)
                    continue
                annexb = payload_to_annexb(payload, length_size)
                self._decode(decoder, annexb)
        except Exception as exc:
            if not self._stop_requested:
                LOGGER.warning("scrcpy video stream stopped: %s", exc)
                self._fail(exc)

    @staticmethod
    def _new_decoder() -> av.CodecContext:
        decoder = av.CodecContext.create("h264", "r")
        decoder.flags |= av.codec.context.Flags.low_delay
        return decoder

    def _decode(self, decoder: av.CodecContext, data: bytes) -> None:
        for packet in decoder.parse(data):
            for frame in decoder.decode(packet):
                image = frame.to_ndarray(format="bgr24")
                success, encoded = cv2.imencode(
                    ".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
                )
                if not success:
                    raise ScreencastError("实时画面编码失败")
                self._publish(encoded.tobytes(), image.shape[1], image.shape[0])

    def _publish(self, jpeg: bytes, width: int, height: int) -> None:
        now = time.monotonic()
        with self._lock:
            self._width = int(width)
            self._height = int(height)
            self._latest_jpeg = jpeg
            self._state = "streaming"
            self._message = ""
            self._frame_times.append(now)
            while self._frame_times and now - self._frame_times[0] > 1.0:
                self._frame_times.popleft()
            self._fps = float(len(self._frame_times))
            subscribers = list(self._subscribers.values())
        for subscriber in subscribers:
            self._offer(subscriber, jpeg)

    def _fail(self, error: Exception) -> None:
        with self._lock:
            if self._stop_requested or self._closing:
                return
            self._closing = True
            self._cleanup_done.clear()
            self._state = "error"
            self._message = str(error) or "实时投屏中断"
            self._fps = 0.0
            subscribers = list(self._subscribers.values())
            connection = self._socket
            process = self._process
            port = self._port
            self._socket = None
            self._process = None
            self._port = None
            self._reader_thread = None
        try:
            for subscriber in subscribers:
                self._offer(subscriber, None)
            self._release(connection, process, port, None, remove_forward=True)
        finally:
            with self._lock:
                self._closing = False
                self._cleanup_done.set()

    def _offer(self, subscriber: FrameSubscriber, frame: bytes | None) -> None:
        frames = subscriber.frames
        try:
            frames.put_nowait(frame)
        except queue.Full:
            try:
                frames.get_nowait()
            except queue.Empty:
                pass
            try:
                frames.put_nowait(frame)
            except queue.Full:
                pass

    def _schedule_idle_stop_locked(self) -> None:
        self._cancel_idle_timer_locked()
        timer = Timer(self.idle_timeout, self._stop_after_idle)
        timer.daemon = True
        self._idle_timer = timer
        timer.start()

    def _schedule_subscriber_guard_locked(self) -> None:
        if self._subscriber_guard is not None:
            return
        timer = Timer(6.0, self._drop_abandoned_subscribers)
        timer.daemon = True
        self._subscriber_guard = timer
        timer.start()

    def _drop_abandoned_subscribers(self) -> None:
        with self._lock:
            self._subscriber_guard = None
            abandoned = [
                subscriber
                for subscriber in self._subscribers.values()
                if subscriber.first_frame_at is None
            ]
            for subscriber in abandoned:
                self._subscribers.pop(subscriber.identifier, None)
            should_stop = (
                not self._subscribers
                and self._reader_thread is not None
                and self._reader_thread.is_alive()
            )
            if should_stop:
                self._schedule_idle_stop_locked()
        for subscriber in abandoned:
            self._offer(subscriber, None)
        for subscriber in abandoned:
            self.unsubscribe(subscriber)

    def _cancel_idle_timer_locked(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None

    def _stop_after_idle(self) -> None:
        with self._lock:
            self._idle_timer = None
            if self._subscribers:
                return
        self.close()

    def _release(
        self,
        connection: socket.socket | None,
        process: subprocess.Popen[str] | None,
        port: int | None,
        reader: Thread | None,
        *,
        remove_forward: bool = True,
    ) -> None:
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                connection.close()
            except OSError:
                pass
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
        if port is not None and remove_forward:
            self._run_adb(
                "forward",
                "--remove",
                f"tcp:{port}",
                check=False,
                timeout=10,
            )
        if reader is not None and reader is not current_thread():
            reader.join(timeout=3)

    def _run_adb(
        self,
        *arguments: str,
        check: bool = True,
        timeout: float = 20,
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                [self.adb_executable, *arguments],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=_creation_flags(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ScreencastError(f"ADB 命令失败：{exc}") from exc
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise ScreencastError(detail or f"ADB 命令失败：{arguments[0]}")
        return result

    def _startup_error(self, prefix: str) -> str:
        details = [line for line in self._log_lines if line.strip()]
        if not details:
            return prefix
        return f"{prefix}：{details[-1]}"
