from __future__ import annotations

import asyncio
from email.parser import BytesParser
from email.policy import default as email_policy
from pathlib import Path
from queue import Empty
import sys
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import quote

import cv2
from fastapi import Body, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool
import numpy as np

from model_automation.config import ConfigError, ConfigStore, PROJECT_ROOT
from model_automation.device import AdbClient, DeviceError
from model_automation.models import AppConfig, Step
from model_automation.operations import (
    ValidationError,
    clone_preset,
    config_from_payload,
    duplicate_preset_name,
    imported_preset_name,
    run_preset_references,
    template_references,
    template_reference_index,
    update_template_reference_resolutions,
    validate_config,
    validate_template_filename,
)
from model_automation.preset_archive import (
    PresetArchiveError,
    export_preset,
    import_preset,
    scale_step,
)
from model_automation.registry import StepRegistry
from model_automation.steps import REGISTRY, step_definitions
from model_automation.vision import acceleration_backend, load_image, set_acceleration

from .runtime import RuntimeConflict, RuntimeManager
from .screencast import ScreencastError, ScrcpyScreencast
from .template_assets import TemplateAssets


MAX_UPLOAD_SIZE = 200 * 1024 * 1024


def _static_root() -> Path:
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(bundled_root) / "web" / "dist"
    return PROJECT_ROOT / "web" / "dist"


def _scrcpy_server_path() -> Path:
    bundled_root = getattr(sys, "_MEIPASS", None)
    root = Path(bundled_root) if bundled_root else PROJECT_ROOT
    return root / "vendor" / "scrcpy-server-v5.0.1"


def _detail(status_code: int, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=message)


def _load_config(store: ConfigStore) -> AppConfig:
    try:
        return store.load()
    except ConfigError as exc:
        raise _detail(400, str(exc)) from exc


def _device_image(device: Any) -> np.ndarray:
    try:
        image = device.screenshot()
    except DeviceError as exc:
        raise _detail(503, str(exc)) from exc
    if not isinstance(image, np.ndarray) or image.ndim < 2 or image.size == 0:
        raise _detail(503, "设备截图无效")
    return image


def _encode_image(image: np.ndarray, suffix: str) -> bytes:
    try:
        success, encoded = cv2.imencode(suffix, image)
    except cv2.error as exc:
        raise _detail(400, f"图片编码失败：{exc}") from exc
    if not success:
        raise _detail(400, "图片编码失败")
    return encoded.tobytes()


def _decode_image(content: bytes) -> np.ndarray:
    if not content:
        raise _detail(400, "图片内容为空")
    try:
        image = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
    except cv2.error as exc:
        raise _detail(400, f"图片无法解码：{exc}") from exc
    if image is None or image.shape[0] <= 0 or image.shape[1] <= 0:
        raise _detail(400, "图片无法解码")
    return image


def _template_name(name: str, *, default_extension: bool = False) -> str:
    candidate = str(name).strip()
    if default_extension and not Path(candidate).suffix:
        candidate += ".png"
    try:
        return validate_template_filename(candidate)
    except ValidationError as exc:
        raise _detail(400, str(exc)) from exc


def _template_path(store: ConfigStore, name: str) -> Path:
    return store.template_dir / _template_name(name)


def _write_atomic(path: Path, content: bytes) -> None:
    temporary = path.with_name(path.name + ".uploading")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(content)
        temporary.replace(path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise _detail(400, f"无法保存文件：{exc}") from exc


async def _uploaded_file(
    request: Request, field_names: tuple[str, ...] = ("file",)
) -> tuple[str, bytes]:
    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > MAX_UPLOAD_SIZE:
            raise _detail(400, "上传文件过大")
        chunks.extend(chunk)
    return await run_in_threadpool(
        _parse_uploaded_file, bytes(chunks), request.headers.get("content-type", ""),
        request.headers.get("x-filename", ""), field_names,
    )


def _parse_uploaded_file(
    content: bytes, content_type: str, filename: str, field_names: tuple[str, ...]
) -> tuple[str, bytes]:
    if content_type.lower().startswith("multipart/form-data"):
        envelope = (
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
            + content
        )
        message = BytesParser(policy=email_policy).parsebytes(envelope)
        for part in message.iter_parts():
            field = part.get_param("name", header="content-disposition")
            filename = part.get_filename()
            if field in field_names and filename:
                return filename, part.get_payload(decode=True) or b""
        raise _detail(400, "上传请求中缺少文件")
    if not filename:
        raise _detail(400, "上传请求中缺少文件名")
    return filename, content


def _rect_crop(image: np.ndarray, raw_rect: Any) -> np.ndarray:
    if not isinstance(raw_rect, dict):
        raise _detail(400, "rect 必须是对象")
    try:
        x = int(raw_rect.get("x"))
        y = int(raw_rect.get("y"))
        width = int(raw_rect.get("width"))
        height = int(raw_rect.get("height"))
    except (TypeError, ValueError) as exc:
        raise _detail(400, "rect 坐标必须是整数") from exc
    if width <= 0 or height <= 0:
        raise _detail(400, "截取区域宽高必须大于 0")
    image_height, image_width = image.shape[:2]
    right = x + width
    bottom = y + height
    if right <= 0 or bottom <= 0 or x >= image_width or y >= image_height:
        raise _detail(400, "截取区域不在截图范围内")
    left = max(0, x)
    top = max(0, y)
    right = min(image_width, right)
    bottom = min(image_height, bottom)
    if right <= left or bottom <= top:
        raise _detail(400, "截取区域无效")
    return image[top:bottom, left:right].copy()


def _threshold(payload: dict[str, Any]) -> float:
    try:
        value = float(payload.get("threshold", 0.8))
    except (TypeError, ValueError) as exc:
        raise _detail(400, "模板阈值无效") from exc
    if not 0.0 <= value <= 1.0:
        raise _detail(400, "模板阈值必须在 0 到 1 之间")
    return value


def _template_record(
    path: Path, image: np.ndarray, references: list[dict[str, str]]
) -> dict[str, Any]:
    height, width = image.shape[:2]
    return {
        "name": path.name,
        "width": int(width),
        "height": int(height),
        "size": path.stat().st_size,
        "references": references,
    }


def _safe_archive_name(name: str) -> str:
    cleaned = "".join(
        "_" if character in '<>:"/\\|?*' or ord(character) < 32 else character
        for character in name
    )
    return cleaned.strip(" .") or "preset"


def create_app(
    config_store: ConfigStore | None = None,
    device: Any | None = None,
    registry: StepRegistry = REGISTRY,
    runtime: RuntimeManager | None = None,
    static_dir: Path | None = None,
    adb: Any | None = None,
    screencast: Any | None = None,
) -> FastAPI:
    store = config_store or (runtime.config_store if runtime is not None else ConfigStore())
    if device is not None and adb is not None:
        raise ValueError("device 和 adb 只能注入一个")
    if device is not None:
        injected_device = device
    elif adb is not None:
        injected_device = adb
    elif runtime is not None:
        injected_device = runtime.device
    else:
        injected_device = AdbClient(PROJECT_ROOT)
    manager = runtime or RuntimeManager(store, injected_device, registry=registry)
    screencast_manager = screencast
    if screencast_manager is None:
        adb_executable = getattr(injected_device, "executable", None)
        if adb_executable:
            screencast_manager = ScrcpyScreencast(
                adb_executable,
                _scrcpy_server_path(),
            )
    assets = TemplateAssets()
    application = FastAPI(title="ADB Automation Web API")
    application.state.config_store = store
    application.state.device = injected_device
    application.state.runtime = manager
    application.state.screencast = screencast_manager
    if screencast_manager is not None:
        close_screencast = getattr(screencast_manager, "close", None)
        if close_screencast is not None:
            application.router.add_event_handler("shutdown", close_screencast)

    @application.exception_handler(RequestValidationError)
    async def request_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        messages = "; ".join(str(item.get("msg", "请求参数无效")) for item in exc.errors())
        return JSONResponse(status_code=400, content={"detail": messages})

    @application.exception_handler(ValidationError)
    @application.exception_handler(ConfigError)
    @application.exception_handler(PresetArchiveError)
    @application.exception_handler(OSError)
    async def data_error(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @application.exception_handler(RuntimeConflict)
    async def runtime_conflict(_request: Request, exc: RuntimeConflict) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @application.exception_handler(DeviceError)
    async def device_error(_request: Request, exc: DeviceError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/device/state")
    def device_state() -> dict[str, Any]:
        try:
            state = injected_device.state()
            if state != "device":
                result = {"connected": False, "state": state, "resolution": None}
                manager.publish_device(result)
                return {**result, "device": result}
            width, height = injected_device.screen_resolution()
            result = {
                "connected": True,
                "state": state,
                "resolution": {"width": width, "height": height},
            }
            manager.publish_device(result)
            return {**result, "device": result}
        except DeviceError as exc:
            result = {
                "connected": False,
                "state": "unavailable",
                "resolution": None,
                "error": str(exc),
            }
            manager.publish_device(result)
            return {**result, "device": result}

    @application.get("/api/device/screenshot")
    def device_screenshot(
        max_width: int | None = Query(default=None, ge=1),
        image_format: str = Query(default="png", alias="format"),
    ) -> Response:
        image = _device_image(injected_device)
        if max_width and image.shape[1] > max_width:
            scale = max_width / image.shape[1]
            height = max(1, int(round(image.shape[0] * scale)))
            image = cv2.resize(image, (max_width, height), interpolation=cv2.INTER_AREA)
        headers = {"Cache-Control": "no-store"}
        if image_format.lower() in {"jpg", "jpeg"}:
            return Response(
                _encode_image(image, ".jpg"),
                media_type="image/jpeg",
                headers=headers,
            )
        if image_format.lower() != "png":
            raise _detail(400, "截图格式仅支持 png 或 jpeg")
        return Response(
            _encode_image(image, ".png"), media_type="image/png", headers=headers
        )

    @application.get("/api/device/stream/status")
    def device_stream_status() -> dict[str, Any]:
        if screencast_manager is None:
            return {
                "state": "unavailable",
                "message": "当前设备不支持实时投屏",
                "codec": None,
                "width": 0,
                "height": 0,
                "fps": 0,
                "subscribers": 0,
            }
        return screencast_manager.status()

    @application.get("/api/device/stream")
    def device_stream(codec: str = Query(default="jpeg")) -> StreamingResponse:
        if codec not in {"jpeg", "h264"}:
            raise _detail(400, "投屏格式仅支持 jpeg 或 h264")
        if screencast_manager is None:
            raise _detail(503, "当前设备不支持实时投屏")
        try:
            if codec == "h264":
                subscribe_h264 = getattr(screencast_manager, "subscribe_h264", None)
                if subscribe_h264 is None:
                    raise _detail(503, "当前投屏服务不支持 H.264 直传")
                subscriber = subscribe_h264()
            else:
                subscriber = screencast_manager.subscribe()
        except ScreencastError as exc:
            raise _detail(503, str(exc)) from exc

        def frames():
            try:
                while True:
                    try:
                        frame = subscriber.frames.get(timeout=1)
                    except Empty:
                        state = screencast_manager.status().get("state")
                        if state in {"error", "idle"}:
                            break
                        continue
                    if frame is None:
                        break
                    screencast_manager.touch(subscriber)
                    yield frame if codec == "h264" else len(frame).to_bytes(4, "big") + frame
            finally:
                screencast_manager.unsubscribe(subscriber)

        return StreamingResponse(
            frames(),
            media_type="application/x-adb-h264; version=1" if codec == "h264" else "application/octet-stream",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
                "X-Accel-Buffering": "no",
                "X-Stream-Format": "h264-packet-v1" if codec == "h264" else "jpeg-length-prefixed",
            },
        )

    @application.get("/api/config")
    def get_config() -> dict[str, Any]:
        return _load_config(store).to_dict()

    @application.put("/api/config")
    def put_config(payload: Any = Body(...)) -> dict[str, Any]:
        with manager.mutation():
            try:
                config = config_from_payload(
                    payload, registry=registry, normalize_dependencies=True
                )
                store.save(config)
            except (ValidationError, ConfigError) as exc:
                raise _detail(400, str(exc)) from exc
            return config.to_dict()

    @application.get("/api/step-definitions")
    def get_step_definitions() -> list[dict[str, Any]]:
        return step_definitions(registry)

    @application.get("/api/presets")
    def presets() -> list[dict[str, Any]]:
        config = _load_config(store)
        return [
            {
                "id": preset.id,
                "name": preset.name,
                "loop_count": preset.loop_count,
                "step_count": len(preset.steps),
                "selected": preset.id == config.selected_preset_id,
            }
            for preset in config.presets
        ]

    @application.post("/api/presets/{preset_id}/duplicate")
    def duplicate_preset(
        preset_id: str, payload: dict[str, Any] | None = Body(default=None)
    ) -> dict[str, Any]:
        with manager.mutation():
            config = _load_config(store)
            source = next((preset for preset in config.presets if preset.id == preset_id), None)
            if source is None:
                raise _detail(404, "找不到预设")
            requested = str((payload or {}).get("name", "")).strip()
            existing_names = [preset.name for preset in config.presets]
            name = requested or duplicate_preset_name(source.name, existing_names)
            if not name:
                raise _detail(400, "预设名称不能为空")
            if name in existing_names:
                raise _detail(400, "已有同名预设")
            duplicate = clone_preset(source, name=name)
            config.presets.append(duplicate)
            config.selected_preset_id = duplicate.id
            store.save(config)
            return {"preset": duplicate.to_dict(), "selected_preset_id": duplicate.id}

    @application.get("/api/presets/{preset_id}/references")
    def preset_reference_list(preset_id: str) -> dict[str, Any]:
        config = _load_config(store)
        if not any(preset.id == preset_id for preset in config.presets):
            raise _detail(404, "找不到预设")
        references = run_preset_references(config.presets, preset_id)
        return {"preset_id": preset_id, "references": references}

    @application.post("/api/run")
    def run(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        preset_id = str(payload.get("preset_id", "")).strip()
        if not preset_id:
            raise _detail(400, "preset_id 不能为空")
        try:
            return manager.start(preset_id)
        except RuntimeConflict as exc:
            raise _detail(409, str(exc)) from exc
        except DeviceError as exc:
            raise _detail(503, str(exc)) from exc
        except (ConfigError, ValueError) as exc:
            raise _detail(400, str(exc)) from exc

    @application.post("/api/stop")
    def stop() -> dict[str, Any]:
        try:
            return manager.stop()
        except RuntimeConflict as exc:
            raise _detail(409, str(exc)) from exc

    @application.get("/api/run/status")
    def run_status() -> dict[str, Any]:
        return manager.status()

    @application.get("/api/templates")
    def templates() -> list[dict[str, Any]]:
        config = _load_config(store)
        store.template_dir.mkdir(parents=True, exist_ok=True)
        references = template_reference_index(config.presets)
        records = []
        for path in sorted(store.template_dir.iterdir(), key=lambda item: item.name.casefold()):
            if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp"}:
                continue
            metadata = assets.metadata(path)
            if metadata is None:
                continue
            records.append({
                "name": path.name, "width": metadata.width, "height": metadata.height,
                "size": metadata.size, "revision": metadata.revision,
                "references": references.get(path.name.casefold(), []),
            })
        return records

    @application.get("/api/templates/{name}/thumbnail")
    def template_thumbnail(
        request: Request, name: str, max_width: int = Query(default=240, ge=1, le=2048)
    ) -> Response:
        thumbnail = assets.thumbnail(_template_path(store, name), max_width)
        if thumbnail is None:
            raise _detail(404, "找不到模板图片")
        content, etag = thumbnail
        headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)
        return Response(content, media_type="image/png", headers=headers)

    @application.post("/api/templates/upload")
    async def upload_template(request: Request) -> dict[str, Any]:
        uploaded_name, content = await _uploaded_file(request)

        def commit() -> dict[str, Any]:
            with manager.mutation():
                filename = _template_name(uploaded_name)
                image = _decode_image(content)
                path = store.template_dir / filename
                _write_atomic(path, content)
                config = _load_config(store)
                return _template_record(path, image, template_references(config.presets, filename))

        return await run_in_threadpool(commit)

    @application.post("/api/templates/capture")
    def capture_template(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        with manager.mutation():
            name = _template_name(str(payload.get("name", "")), default_extension=True)
            threshold = _threshold(payload)
            screen = _device_image(injected_device)
            cropped = _rect_crop(screen, payload.get("rect"))
            content = _encode_image(cropped, Path(name).suffix.lower())
            path = store.template_dir / name
            _write_atomic(path, content)
            config = _load_config(store)
            record = _template_record(path, cropped, template_references(config.presets, name))
            record["threshold"] = threshold
            return record

    @application.post("/api/templates/{name}/recapture")
    def recapture_template(
        name: str, payload: dict[str, Any] = Body(...)
    ) -> dict[str, Any]:
        with manager.mutation():
            name = _template_name(name)
            threshold = _threshold(payload)
            path = store.template_dir / name
            if not path.exists():
                raise _detail(404, "找不到模板图片")
            screen = _device_image(injected_device)
            cropped = _rect_crop(screen, payload.get("rect"))
            content = _encode_image(cropped, path.suffix.lower())
            _write_atomic(path, content)
            config = _load_config(store)
            height, width = screen.shape[:2]
            updated = update_template_reference_resolutions(
                config.presets, name, (int(width), int(height))
            )
            store.save(config)
            record = _template_record(path, cropped, template_references(config.presets, name))
            record.update({"threshold": threshold, "updated_references": updated})
            return record

    @application.delete("/api/templates/{name}")
    def delete_template(name: str) -> dict[str, Any]:
        with manager.mutation():
            name = _template_name(name)
            path = store.template_dir / name
            config = _load_config(store)
            references = template_references(config.presets, name)
            try:
                path.unlink()
            except FileNotFoundError as exc:
                raise _detail(404, "找不到模板图片") from exc
            except OSError as exc:
                raise _detail(400, f"无法删除模板：{exc}") from exc
            return {"deleted": name, "references": references}

    @application.get("/api/archive/export")
    def archive_export(preset_id: str = Query(...)) -> Response:
        with manager.mutation():
            config = _load_config(store)
            preset = next((item for item in config.presets if item.id == preset_id), None)
            if preset is None:
                raise _detail(404, "找不到预设")
            with TemporaryDirectory() as directory:
                destination = Path(directory) / "preset.adb-preset.zip"
                try:
                    export_preset(preset, store.template_dir, destination)
                    content = destination.read_bytes()
                except PresetArchiveError as exc:
                    raise _detail(400, str(exc)) from exc
            filename = f"{_safe_archive_name(preset.name)}.adb-preset.zip"
            disposition = f"attachment; filename*=UTF-8''{quote(filename)}"
            return Response(
                content,
                media_type="application/zip",
                headers={"Content-Disposition": disposition},
            )

    @application.post("/api/archive/import")
    async def archive_import(request: Request) -> dict[str, Any]:
        filename, content = await _uploaded_file(request, ("file", "archive"))

        def commit() -> dict[str, Any]:
            with manager.mutation():
                if not filename.lower().endswith(".zip"):
                    raise _detail(400, "预设包必须是 ZIP 文件")
                try:
                    resolution = (injected_device.screen_resolution(refresh=True)
                                  if isinstance(injected_device, AdbClient)
                                  else injected_device.screen_resolution())
                except DeviceError as exc:
                    raise _detail(503, str(exc)) from exc
                with TemporaryDirectory() as directory:
                    source = Path(directory) / "preset.zip"
                    source.write_bytes(content)
                    try:
                        preset = import_preset(source, store.template_dir, resolution)
                    except PresetArchiveError as exc:
                        raise _detail(400, str(exc)) from exc
                config = _load_config(store)
                preset.name = imported_preset_name(
                    preset.name, [item.name for item in config.presets]
                )
                config.presets.append(preset)
                config.selected_preset_id = preset.id
                try:
                    validate_config(config, registry=registry)
                    store.save(config)
                except (ValidationError, ConfigError) as exc:
                    raise _detail(400, str(exc)) from exc
                return {
                    "preset": preset.to_dict(),
                    "selected_preset_id": preset.id,
                    "resolution": {"width": resolution[0], "height": resolution[1]},
                }

        return await run_in_threadpool(commit)

    @application.put("/api/settings/acceleration")
    def acceleration(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        with manager.mutation():
            requested = str(payload.get("acceleration", payload.get("mode", ""))).strip()
            try:
                applied = set_acceleration(requested)
            except ValueError as exc:
                raise _detail(400, str(exc)) from exc
            config = _load_config(store)
            config.acceleration = applied
            store.save(config)
            return {
                "requested": requested,
                "applied": applied,
                "acceleration": applied,
                "backend": acceleration_backend(),
                "fallback": requested != applied,
            }

    @application.post("/api/coords/scale")
    def coordinates_scale(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        raw_step = payload.get("step")
        raw_resolution = payload.get("target_resolution")
        if not isinstance(raw_step, dict) or not isinstance(raw_resolution, dict):
            raise _detail(400, "step 和 target_resolution 必须是对象")
        try:
            width = int(raw_resolution.get("width", 0))
            height = int(raw_resolution.get("height", 0))
            if width <= 0 or height <= 0:
                raise ValueError
            scaled = scale_step(Step.from_dict(raw_step), (width, height))
        except (TypeError, ValueError, PresetArchiveError) as exc:
            raise _detail(400, str(exc) or "目标分辨率无效") from exc
        return scaled.to_dict()

    @application.websocket("/ws/events")
    async def events_socket(websocket: WebSocket) -> None:
        await websocket.accept()
        backlog, queue, subscriber = await manager.subscribe()
        async def send_events() -> None:
            for event in backlog:
                await asyncio.wait_for(websocket.send_json(event), timeout=10)
            while True:
                await asyncio.wait_for(websocket.send_json(await queue.get()), timeout=10)

        async def receive_disconnect() -> None:
            while True:
                if (await websocket.receive())["type"] == "websocket.disconnect":
                    return

        tasks = [asyncio.create_task(send_events()),
                 asyncio.create_task(receive_disconnect()),
                 asyncio.create_task(subscriber.closed.wait())]
        try:
            done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            if subscriber.closed.is_set():
                tasks[0].cancel()
                await asyncio.gather(tasks[0], return_exceptions=True)
                await websocket.close(code=1013, reason="事件消费过慢，请重新连接")
        except asyncio.TimeoutError:
            await websocket.close(code=1013, reason="事件发送超时，请重新连接")
        except (WebSocketDisconnect, OSError):
            pass
        finally:
            manager.unsubscribe(subscriber)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    dist = (static_dir or _static_root()).resolve()
    if dist.is_dir():
        index = dist / "index.html"

        @application.get("/{full_path:path}", include_in_schema=False)
        def static_files(full_path: str) -> FileResponse:
            if full_path.startswith(("api/", "ws/")):
                raise _detail(404, "文件不存在")
            requested = (dist / full_path).resolve()
            try:
                requested.relative_to(dist)
            except ValueError as exc:
                raise _detail(404, "文件不存在") from exc
            if requested.is_file():
                return FileResponse(requested)
            if index.is_file():
                return FileResponse(index)
            raise _detail(404, "文件不存在")

    return application


app = create_app()
