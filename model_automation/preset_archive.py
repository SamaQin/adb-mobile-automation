from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

import cv2
import numpy as np

from .models import Preset, Step
from .operations import (
    ValidationError,
    iter_steps,
    remap_preset_ids,
    validate_preset_structure,
    validate_template_filename,
)
from .steps import REGISTRY


ARCHIVE_VERSION = 1
MANIFEST_NAME = "manifest.json"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp"}
MAX_ARCHIVE_MEMBER_SIZE = 50 * 1024 * 1024
MAX_ARCHIVE_TOTAL_SIZE = 200 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 1000


class PresetArchiveError(RuntimeError):
    pass


def _iter_steps(preset: Preset):
    yield from iter_steps(preset)


def _template_names(preset: Preset) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for step in _iter_steps(preset):
        templates = step.params.get("templates", [])
        for item in templates if isinstance(templates, list) else []:
            if not isinstance(item, dict):
                continue
            filename = str(item.get("file", "")).strip()
            if not filename or filename in seen:
                continue
            _validate_template_name(filename)
            names.append(filename)
            seen.add(filename)
    return names


def _validate_template_name(filename: str) -> None:
    try:
        validate_template_filename(filename)
    except ValidationError as exc:
        raise PresetArchiveError(str(exc)) from exc


def _validate_preset_for_export(preset: Preset) -> None:
    try:
        validate_preset_structure(preset)
    except ValidationError as exc:
        raise PresetArchiveError(str(exc)) from exc
    missing_resolution: list[str] = []
    for step in _iter_steps(preset):
        definition = REGISTRY.get(step.kind)
        if definition is None:
            raise PresetArchiveError(f"不支持的步骤类型：{step.kind}")
        needs_resolution = any(
            field.coordinate_axis or field.kind == "templates"
            for field in definition.fields
        )
        if needs_resolution and step.screen_resolution is None:
            missing_resolution.append(step.name)
    if missing_resolution:
        raise PresetArchiveError(
            "以下步骤没有记录屏幕分辨率，请逐个编辑并保存后再导出："
            + "、".join(missing_resolution)
        )


def export_preset(preset: Preset, template_dir: Path, destination: Path) -> None:
    _validate_preset_for_export(preset)
    assets = []
    contents: dict[str, bytes] = {}
    missing: list[str] = []
    for filename in _template_names(preset):
        path = template_dir / filename
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            missing.append(filename)
            continue
        except OSError as exc:
            raise PresetArchiveError(f"无法读取模板 {filename}：{exc}") from exc
        archive_path = f"assets/{filename}"
        contents[archive_path] = content
        assets.append(
            {
                "name": filename,
                "path": archive_path,
                "sha256": sha256(content).hexdigest(),
            }
        )
    if missing:
        raise PresetArchiveError("找不到预设使用的模板：" + "、".join(missing))

    manifest = {
        "archive_version": ARCHIVE_VERSION,
        "preset": preset.to_dict(),
        "assets": assets,
    }
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr(
                MANIFEST_NAME,
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
            for archive_path, content in contents.items():
                archive.writestr(archive_path, content)
        temporary.replace(destination)
    except (OSError, BadZipFile) as exc:
        raise PresetArchiveError(f"无法导出预设包：{exc}") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _read_archive(source: Path) -> tuple[Preset, dict[str, bytes]]:
    try:
        with ZipFile(source, "r") as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise PresetArchiveError("预设包包含重复文件")
            if MANIFEST_NAME not in names:
                raise PresetArchiveError("预设包缺少 manifest.json")
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_MEMBERS:
                raise PresetArchiveError("预设包包含过多文件")
            if sum(info.file_size for info in infos) > MAX_ARCHIVE_TOTAL_SIZE:
                raise PresetArchiveError("预设包内容过大")
            for info in infos:
                if info.file_size > MAX_ARCHIVE_MEMBER_SIZE:
                    raise PresetArchiveError(f"预设包文件过大：{info.filename}")
            try:
                manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise PresetArchiveError(f"预设包清单无效：{exc}") from exc
            if not isinstance(manifest, dict):
                raise PresetArchiveError("预设包清单必须是对象")
            if int(manifest.get("archive_version", 0)) != ARCHIVE_VERSION:
                raise PresetArchiveError("不支持该预设包版本")
            raw_preset = manifest.get("preset")
            if not isinstance(raw_preset, dict):
                raise PresetArchiveError("预设包中的预设数据无效")
            preset = Preset.from_dict(raw_preset)

            assets: dict[str, bytes] = {}
            raw_assets = manifest.get("assets", [])
            if not isinstance(raw_assets, list):
                raise PresetArchiveError("预设包图片清单无效")
            for item in raw_assets:
                if not isinstance(item, dict):
                    raise PresetArchiveError("预设包图片记录无效")
                filename = str(item.get("name", ""))
                archive_path = str(item.get("path", ""))
                expected_hash = str(item.get("sha256", ""))
                _validate_template_name(filename)
                if archive_path != f"assets/{filename}" or archive_path not in names:
                    raise PresetArchiveError(f"预设包缺少模板：{filename}")
                content = archive.read(archive_path)
                if sha256(content).hexdigest() != expected_hash:
                    raise PresetArchiveError(f"模板校验失败：{filename}")
                if filename in assets:
                    raise PresetArchiveError(f"模板记录重复：{filename}")
                assets[filename] = content
    except PresetArchiveError:
        raise
    except (AttributeError, OSError, BadZipFile, RuntimeError, TypeError, ValueError) as exc:
        raise PresetArchiveError(f"无法读取预设包：{exc}") from exc

    referenced = set(_template_names(preset))
    missing = referenced.difference(assets)
    if missing:
        raise PresetArchiveError("预设包缺少模板：" + "、".join(sorted(missing)))
    return preset, assets


def _scale_step(step: Step, target_resolution: tuple[int, int]) -> tuple[float, float]:
    definition = REGISTRY.get(step.kind)
    if definition is None:
        raise PresetArchiveError(f"不支持的步骤类型：{step.kind}")
    coordinate_fields = [field for field in definition.fields if field.coordinate_axis]
    uses_templates = any(field.kind == "templates" for field in definition.fields)
    if (coordinate_fields or uses_templates) and step.screen_resolution is None:
        raise PresetArchiveError(f"步骤“{step.name}”没有记录屏幕分辨率，无法缩放")

    source_width, source_height = step.screen_resolution or target_resolution
    target_width, target_height = target_resolution
    scale_x = target_width / source_width
    scale_y = target_height / source_height
    for field in coordinate_fields:
        try:
            value = int(step.params.get(field.key, field.default))
        except (TypeError, ValueError) as exc:
            raise PresetArchiveError(
                f"步骤“{step.name}”的坐标 {field.key} 无效"
            ) from exc
        scale = scale_x if field.coordinate_axis == "x" else scale_y
        scaled = int(round(value * scale))
        if not field.coordinate_offset:
            maximum = target_width - 1 if field.coordinate_axis == "x" else target_height - 1
            scaled = max(0, min(maximum, scaled))
        step.params[field.key] = scaled
    step.screen_resolution = target_resolution
    return scale_x, scale_y


def scale_step(step: Step, target_resolution: tuple[int, int]) -> Step:
    """Return a scaled deep copy, including all nested branch steps."""
    try:
        target_width, target_height = map(int, target_resolution)
    except (TypeError, ValueError) as exc:
        raise PresetArchiveError("目标屏幕分辨率无效") from exc
    if target_width <= 0 or target_height <= 0:
        raise PresetArchiveError("目标屏幕分辨率必须大于 0")
    target = (target_width, target_height)
    try:
        validate_preset_structure(
            Preset(name="scale", steps=[step]), strict_dependencies=False
        )
    except ValidationError as exc:
        raise PresetArchiveError(str(exc)) from exc
    scaled = Step.from_dict(deepcopy(step.to_dict()))
    _scale_step(scaled, target)
    branches = scaled.params.get("branches", {})
    if isinstance(branches, dict):
        for raw_steps in branches.values():
            if not isinstance(raw_steps, list):
                continue
            for index, raw in enumerate(raw_steps):
                if not isinstance(raw, dict):
                    continue
                raw_steps[index] = scale_step(
                    Step.from_dict(raw), target
                ).to_dict()
    return scaled


def _template_resolution(
    item: dict[str, object], fallback: tuple[int, int]
) -> tuple[int, int]:
    raw_resolution = item.get("screen_resolution")
    if raw_resolution is None:
        return fallback
    if not isinstance(raw_resolution, dict):
        raise PresetArchiveError("模板屏幕分辨率必须是对象")
    try:
        width = int(raw_resolution.get("width", 0))
        height = int(raw_resolution.get("height", 0))
    except (TypeError, ValueError) as exc:
        raise PresetArchiveError("模板屏幕分辨率无效") from exc
    if width <= 0 or height <= 0:
        raise PresetArchiveError("模板屏幕分辨率必须大于 0")
    return width, height


def _scaled_image(content: bytes, scale_x: float, scale_y: float, suffix: str) -> bytes:
    data = np.frombuffer(content, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise PresetArchiveError("模板图片无法解码")
    if scale_x == 1.0 and scale_y == 1.0:
        return content
    width = max(1, int(round(image.shape[1] * scale_x)))
    height = max(1, int(round(image.shape[0] * scale_y)))
    interpolation = cv2.INTER_AREA if scale_x < 1.0 or scale_y < 1.0 else cv2.INTER_CUBIC
    resized = cv2.resize(image, (width, height), interpolation=interpolation)
    success, encoded = cv2.imencode(suffix, resized)
    if not success:
        raise PresetArchiveError("缩放后的模板图片无法编码")
    return encoded.tobytes()


def _available_filename(
    preferred: str,
    content: bytes,
    existing: dict[str, tuple[str, bytes]],
    planned: dict[str, tuple[str, bytes]],
) -> str:
    key = preferred.casefold()
    match = planned.get(key) or existing.get(key)
    if match is None:
        return preferred
    if match[1] == content:
        return match[0]

    path = Path(preferred)
    index = 1
    while True:
        suffix = "_imported" if index == 1 else f"_imported_{index}"
        candidate = f"{path.stem}{suffix}{path.suffix}"
        key = candidate.casefold()
        match = planned.get(key) or existing.get(key)
        if match is None:
            return candidate
        if match[1] == content:
            return match[0]
        index += 1


def _prepare_step(
    step: Step,
    target_width: int,
    target_height: int,
    existing: dict[str, tuple[str, bytes]],
    planned: dict[str, tuple[str, bytes]],
    variants: dict[tuple[str, int, int], str],
    assets: dict[str, bytes],
) -> None:
    source_resolution = step.screen_resolution
    _scale_step(step, (target_width, target_height))
    templates = step.params.get("templates", [])
    for item in templates if isinstance(templates, list) else []:
        if not isinstance(item, dict):
            continue
        filename = str(item.get("file", ""))
        source_width, source_height = _template_resolution(
            item, source_resolution or (target_width, target_height)
        )
        scale_x = target_width / source_width
        scale_y = target_height / source_height
        variant_key = (filename, source_width, source_height)
        destination_name = variants.get(variant_key)
        if destination_name is None:
            try:
                content = _scaled_image(
                    assets[filename], scale_x, scale_y, Path(filename).suffix.lower()
                )
            except KeyError as exc:
                raise PresetArchiveError(f"预设包缺少模板：{filename}") from exc
            destination_name = _available_filename(filename, content, existing, planned)
            variants[variant_key] = destination_name
            if destination_name.casefold() not in existing:
                planned[destination_name.casefold()] = (destination_name, content)
        item["file"] = destination_name
        item["screen_resolution"] = {
            "width": target_width,
            "height": target_height,
        }
    branches = step.params.get("branches", {})
    if isinstance(branches, dict):
        for key, raw_list in branches.items():
            if not isinstance(raw_list, list):
                continue
            for index, raw in enumerate(raw_list):
                if not isinstance(raw, dict):
                    continue
                branch_step = Step.from_dict(raw)
                _prepare_step(
                    branch_step,
                    target_width,
                    target_height,
                    existing,
                    planned,
                    variants,
                    assets,
                )
                raw_list[index] = branch_step.to_dict()


def import_preset(
    source: Path,
    template_dir: Path,
    target_resolution: tuple[int, int],
) -> Preset:
    target_width, target_height = map(int, target_resolution)
    if target_width <= 0 or target_height <= 0:
        raise PresetArchiveError("当前设备分辨率无效")
    preset, assets = _read_archive(source)
    existing: dict[str, tuple[str, bytes]] = {}
    if template_dir.exists():
        try:
            for path in template_dir.iterdir():
                if path.is_file():
                    existing[path.name.casefold()] = (path.name, path.read_bytes())
        except OSError as exc:
            raise PresetArchiveError(f"无法读取模板目录：{exc}") from exc

    planned: dict[str, tuple[str, bytes]] = {}
    variants: dict[tuple[str, int, int], str] = {}
    for step in preset.steps:
        _prepare_step(
            step,
            target_width,
            target_height,
            existing,
            planned,
            variants,
            assets,
        )

    try:
        remap_preset_ids(preset, strict_dependencies=True)
    except ValidationError as exc:
        message = str(exc)
        if message == "包含重复的步骤 ID":
            message = "预设包包含重复的步骤 ID"
        raise PresetArchiveError(message) from exc

    temporary_paths: list[tuple[Path, Path]] = []
    try:
        template_dir.mkdir(parents=True, exist_ok=True)
        for filename, content in planned.values():
            destination = template_dir / filename
            temporary = destination.with_name(destination.name + ".importing")
            temporary.write_bytes(content)
            temporary_paths.append((temporary, destination))
        for temporary, destination in temporary_paths:
            temporary.replace(destination)
    except OSError as exc:
        for temporary, _destination in temporary_paths:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise PresetArchiveError(f"无法写入模板图片：{exc}") from exc
    return preset
