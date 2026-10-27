from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
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
_CURRENT_DEVICE = object()

SCRCPY_VERSION = "5.0.1"
SCRCPY_REMOTE_PATH = "/data/local/tmp/adb-automation-scrcpy-5.0.1.jar"
H264_CODEC_ID = 0x68323634
MAX_PACKET_SIZE = 16 * 1024 * 1024
STREAM_SESSION_FLAG = 1 << 63
PACKET_CONFIG_FLAG = 1 << 62
PACKET_KEY_FRAME_FLAG = 1 << 61
PACKET_PTS_MASK = (1 << 61) - 1
JPEG_QUALITY = 82
H264_QUEUE_SIZE = 32
H264_CONTENT_TYPE = "application/x-adb-h264; version=1"


def encode_session(width: int, height: int) -> bytes:
    """Wire v1: a 12-byte session header, followed by config/keyframe packets."""
    return (0x80000000).to_bytes(4, "big") + width.to_bytes(4, "big") + height.to_bytes(4, "big")


def encode_packet(payload: bytes, pts: int = 0, *, config: bool = False, key_frame: bool = False) -> bytes:
    flags = pts & PACKET_PTS_MASK
    if config:
        flags |= PACKET_CONFIG_FLAG
    if key_frame:
        flags |= PACKET_KEY_FRAME_FLAG
    return flags.to_bytes(8, "big") + len(payload).to_bytes(4, "big") + payload


def annexb_nals(data: bytes) -> list[bytes]:
    import re
    return [nal for nal in re.split(b"\x00\x00(?:\x00)?\x01", data) if nal]


def has_parameter_sets(data: bytes) -> bool:
    kinds = {nal[0] & 0x1F for nal in annexb_nals(data)}
    return {7, 8}.issubset(kinds)


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
    codec: str = "jpeg"
    waiting_keyframe: bool = True
    created_at: float = field(default_factory=time.monotonic)


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
        self._device_change_lock = RLock()
        self._device_ready = Event()
        self._device_ready.set()
        self._switching_device = False
        self._serial: str | None = None
        self._stream_serial: str | None = None
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
        self._h264_config: bytes | None = None
        self._config_revision = 0
        self._gop: list[tuple[bytes, int, bool]] = []
        self._gop_bytes = 0
        self._jpeg_decoder = None
        self._device_name = ""
        self._log_lines: deque[str] = deque(maxlen=40)

    def set_device(self, serial: str | None) -> None:
        """Close the old stream atomically before future subscribers use serial."""
        if serial is not None and (not isinstance(serial, str) or not serial or serial.startswith("-") or any(char.isspace() for char in serial)):
            raise ScreencastError("投屏设备序列号无效")
        with self._device_change_lock:
            with self._lock:
                if self._serial == serial:
                    return
                self._switching_device = True
                self._device_ready.clear()
            try:
                # A reader failure may already be releasing this stream. Its
                # cleanup must finish before the selected serial can change.
                self._cleanup_done.wait()
                self.close()
                self._cleanup_done.wait()
                with self._lock:
                    self._serial = serial
                    self._device_name = ""
                    self._width = self._height = 0
            finally:
                with self._lock:
                    self._switching_device = False
                    self._device_ready.set()

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

    def subscribe(self, codec: str = "jpeg") -> FrameSubscriber:
        if codec not in {"jpeg", "h264"}:
            raise ScreencastError(f"不支持的投屏编码：{codec}")
        while True:
            self._device_ready.wait(timeout=5)
            self._cleanup_done.wait(timeout=5)
            with self._lock:
                if self._closing or self._switching_device:
                    continue
                self._cancel_idle_timer_locked()
                if self._reader_thread is None or not self._reader_thread.is_alive():
                    self._start_locked()
                subscriber = FrameSubscriber(
                    self._next_subscriber,
                    queue.Queue(maxsize=H264_QUEUE_SIZE if codec == "h264" else 1),
                    codec=codec,
                )
                self._next_subscriber += 1
                self._subscribers[subscriber.identifier] = subscriber
                if codec == "h264" and self._gop and self._h264_config:
                    self._offer(subscriber, self._bootstrap_locked())
                    subscriber.waiting_keyframe = False
                if codec == "jpeg":
                    if self._latest_jpeg is None and self._gop and self._h264_config:
                        self._jpeg_decoder = self._new_decoder()
                        self._decode(self._jpeg_decoder, self._h264_config)
                        for payload, _pts, _key in self._gop:
                            self._decode(self._jpeg_decoder, payload)
                    if self._latest_jpeg is not None:
                        self._offer(subscriber, self._latest_jpeg)
                self._schedule_subscriber_guard_locked()
                return subscriber

    def subscribe_h264(self) -> FrameSubscriber:
        return self.subscribe(codec="h264")

    def touch(self, subscriber: FrameSubscriber) -> None:
        with self._lock:
            current = self._subscribers.get(subscriber.identifier)
            if current is not None and current.first_frame_at is None:
                current.first_frame_at = time.monotonic()

    def unsubscribe(self, subscriber: FrameSubscriber) -> None:
        with self._lock:
            self._subscribers.pop(subscriber.identifier, None)
            if not any(sub.codec == "jpeg" for sub in self._subscribers.values()):
                self._jpeg_decoder = None
                self._latest_jpeg = None
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

    def close(self, *, only_if_idle: bool = False) -> None:
        with self._lock:
            if self._closing or (only_if_idle and self._subscribers):
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
            serial = self._stream_serial
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
            self._h264_config = None
            self._gop.clear()
            self._gop_bytes = 0
            self._jpeg_decoder = None
        try:
            for subscriber in subscribers:
                self._offer(subscriber, None)
            self._release(connection, process, port, reader, serial=serial)
        finally:
            with self._lock:
                self._closing = False
                self._cleanup_done.set()

    def _start_locked(self) -> None:
        self._stream_serial = self._serial
        serial = self._stream_serial
        self._state = "starting"
        self._message = ""
        self._width = 0
        self._height = 0
        self._fps = 0.0
        self._frame_times.clear()
        self._latest_jpeg = None
        self._h264_config = None
        self._gop.clear()
        self._gop_bytes = 0
        self._jpeg_decoder = None
        self._log_lines.clear()
        self._stop_requested = False
        connection: socket.socket | None = None
        process: subprocess.Popen[str] | None = None
        port: int | None = None
        try:
            self._push_server()
            serial = self._stream_serial
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
            self._release(connection, process, port, None, remove_forward=True, serial=serial)
            raise ScreencastError(self._message) from exc

    def _push_server(self) -> None:
        if not self.server_path.is_file():
            raise ScreencastError(
                "找不到 scrcpy 投屏服务文件，请重新安装完整版本"
            )
        if self._stream_serial is None:
            # Preserve the single-device default, but pin its actual serial for
            # the complete stream lifetime, including cleanup after a later connect.
            result = self._run_adb("devices", "-l")
            available = []
            for line in result.stdout.splitlines():
                fields = line.split()
                if len(fields) >= 2 and fields[1] == "device":
                    available.append(fields[0])
            if len(available) != 1:
                raise ScreencastError("请先选择一个可用的 ADB 设备再启动投屏")
            self._stream_serial = available[0]
        self._run_adb("push", str(self.server_path), SCRCPY_REMOTE_PATH, timeout=30)

    def _launch_server(self, scid: int) -> subprocess.Popen[str]:
        arguments = [
            self.adb_executable,
            *(["-s", self._stream_serial] if self._stream_serial is not None else []),
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
            # Android MediaFormat options: bound GOP length and keep static displays
            # producing frames, so an exhausted replay cache can recover.
            "video_codec_options=i-frame-interval=1,repeat-previous-frame-after:long=100000",
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
        length_size = 4
        try:
            while True:
                header = parse_stream_header(_recv_exact(connection, 12))
                if isinstance(header, StreamSession):
                    self._set_session(header)
                    length_size = 4
                    continue
                payload = _recv_exact(connection, header.size)
                if header.config:
                    annexb, length_size = config_to_annexb(payload)
                    self._set_config(annexb)
                    continue
                annexb = payload_to_annexb(payload, length_size)
                # A keyframe can carry the parameter sets in-band as well.
                parameter_sets = [nal for nal in annexb_nals(annexb) if nal[0] & 0x1F in {7, 8}]
                if {nal[0] & 0x1F for nal in parameter_sets} == {7, 8}:
                    self._set_config(b"".join(b"\x00\x00\x00\x01" + nal for nal in parameter_sets))
                key_frame = header.key_frame or any(nal[0] & 0x1F == 5 for nal in annexb_nals(annexb))
                with self._lock:
                    self._publish_h264(annexb, header.pts, key_frame)
                    wants_jpeg = any(sub.codec == "jpeg" for sub in self._subscribers.values())
                    if not wants_jpeg:
                        self._jpeg_decoder = None
                        continue
                    if self._jpeg_decoder is None:
                        if not self._gop or self._h264_config is None:
                            continue
                        self._jpeg_decoder = self._new_decoder()
                        self._decode(self._jpeg_decoder, self._h264_config)
                        for cached, _pts, _key in self._gop:
                            self._decode(self._jpeg_decoder, cached)
                    else:
                        self._decode(self._jpeg_decoder, annexb)
        except Exception as exc:
            if not self._stop_requested:
                LOGGER.warning("scrcpy video stream stopped: %s", exc)
                self._fail(exc)

    def _set_session(self, session: StreamSession) -> None:
        with self._lock:
            self._width, self._height = session.width, session.height
            self._latest_jpeg = None
            self._h264_config = None
            self._config_revision += 1
            self._resync_h264_locked()

    def _set_config(self, config: bytes) -> None:
        if not has_parameter_sets(config):
            raise ScreencastError("H.264 配置缺少 SPS/PPS")
        with self._lock:
            if config == self._h264_config:
                return
            self._h264_config = config
            self._config_revision += 1
            self._resync_h264_locked()

    @staticmethod
    def _empty_queue(subscriber: FrameSubscriber) -> None:
        while True:
            try:
                subscriber.frames.get_nowait()
            except queue.Empty:
                return

    def _resync_h264_locked(self) -> None:
        self._gop.clear()
        self._gop_bytes = 0
        self._jpeg_decoder = None
        self._latest_jpeg = None
        for subscriber in self._subscribers.values():
            if subscriber.codec == "h264":
                self._empty_queue(subscriber)
                subscriber.waiting_keyframe = True

    def _bootstrap_locked(self) -> bytes:
        return (encode_session(self._width, self._height)
                + encode_packet(self._h264_config, config=True)
                + b"".join(encode_packet(data, pts, key_frame=key) for data, pts, key in self._gop))

    def _publish_h264(self, payload: bytes, pts: int, key_frame: bool) -> None:
        with self._lock:
            if key_frame:
                self._gop.clear()
                self._gop_bytes = 0
            if key_frame or self._gop:
                self._gop.append((payload, pts, key_frame))
                self._gop_bytes += len(payload)
                if len(self._gop) > 120 or self._gop_bytes > 8 * 1024 * 1024:
                    self._gop.clear()
                    self._gop_bytes = 0
            self._record_frame_locked()
            packet: bytes | None = None
            bootstrap: bytes | None = None
            for subscriber in self._subscribers.values():
                if subscriber.codec != "h264":
                    continue
                if subscriber.frames.full():
                    self._empty_queue(subscriber)
                    subscriber.waiting_keyframe = True
                if subscriber.waiting_keyframe:
                    if not key_frame or self._h264_config is None:
                        continue
                    if bootstrap is None:
                        if packet is None:
                            packet = encode_packet(payload, pts, key_frame=key_frame)
                        bootstrap = (encode_session(self._width, self._height)
                                     + encode_packet(self._h264_config, config=True) + packet)
                    frame = bootstrap
                    subscriber.waiting_keyframe = False
                else:
                    if packet is None:
                        packet = encode_packet(payload, pts, key_frame=key_frame)
                    frame = packet
                subscriber.frames.put_nowait(frame)

    def _record_frame_locked(self) -> None:
        now = time.monotonic()
        self._state = "streaming"
        self._message = ""
        self._frame_times.append(now)
        while self._frame_times and now - self._frame_times[0] > 1.0:
            self._frame_times.popleft()
        self._fps = float(len(self._frame_times))

    @staticmethod
    def _new_decoder() -> av.CodecContext:
        decoder = av.CodecContext.create("h264", "r")
        decoder.flags |= av.codec.context.Flags.low_delay
        return decoder

    def _decode(self, decoder: av.CodecContext, data: bytes) -> None:
        if not any(nal[0] & 0x1F in {1, 5} for nal in annexb_nals(data)):
            decoder.extradata = data
            return
        # scrcpy packets already contain a complete access unit. Avoid parse(),
        # which retains the final frame until a later packet on a static display.
        for frame in decoder.decode(av.Packet(data)):
            image = frame.to_ndarray(format="bgr24")
            success, encoded = cv2.imencode(
                ".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
            )
            if not success:
                raise ScreencastError("实时画面编码失败")
            self._publish(encoded.tobytes(), image.shape[1], image.shape[0])

    def _publish(self, jpeg: bytes, width: int, height: int) -> None:
        with self._lock:
            self._width = int(width)
            self._height = int(height)
            self._latest_jpeg = jpeg
            subscribers = [sub for sub in self._subscribers.values() if sub.codec == "jpeg"]
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
            serial = self._stream_serial
            self._socket = None
            self._process = None
            self._port = None
            self._reader_thread = None
        try:
            for subscriber in subscribers:
                self._offer(subscriber, None)
            self._release(connection, process, port, None, remove_forward=True, serial=serial)
        finally:
            with self._lock:
                self._closing = False
                self._cleanup_done.set()

    def _offer(self, subscriber: FrameSubscriber, frame: bytes | None) -> None:
        frames = subscriber.frames
        if frame is None:
            self._empty_queue(subscriber)
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
        pending = [sub for sub in self._subscribers.values() if sub.first_frame_at is None]
        if not pending:
            return
        delay = max(0.05, min(sub.created_at + 15.0 for sub in pending) - time.monotonic())
        timer = Timer(delay, self._drop_abandoned_subscribers)
        timer.daemon = True
        self._subscriber_guard = timer
        timer.start()

    def _drop_abandoned_subscribers(self) -> None:
        with self._lock:
            self._subscriber_guard = None
            abandoned = [
                subscriber
                for subscriber in self._subscribers.values()
                if subscriber.first_frame_at is None and time.monotonic() - subscriber.created_at >= 15.0
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
            self._schedule_subscriber_guard_locked()
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
        self.close(only_if_idle=True)

    def _release(
        self,
        connection: socket.socket | None,
        process: subprocess.Popen[str] | None,
        port: int | None,
        reader: Thread | None,
        *,
        remove_forward: bool = True,
        serial: str | None | object = _CURRENT_DEVICE,
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
                serial=serial,
            )
        if reader is not None and reader is not current_thread():
            reader.join(timeout=3)

    def _run_adb(
        self,
        *arguments: str,
        check: bool = True,
        timeout: float = 20,
        serial: str | None | object = _CURRENT_DEVICE,
    ) -> subprocess.CompletedProcess[str]:
        target = self._stream_serial if serial is _CURRENT_DEVICE else serial
        prefix = ["-s", target] if target is not None else []
        if arguments[0] == "devices":
            prefix = []
        try:
            result = subprocess.run(
                [self.adb_executable, *prefix, *arguments],
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
