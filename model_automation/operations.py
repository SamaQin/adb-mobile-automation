from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from .models import AppConfig, Preset, Step, canonical_step_kind, new_id
from .registry import StepRegistry


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp"}


class ValidationError(ValueError):
    pass


def validate_template_filename(filename: str) -> str:
    filename = str(filename).strip()
    if (
        not filename
        or filename != Path(filename).name
        or "/" in filename
        or "\\" in filename
    ):
        raise ValidationError(f"模板文件名无效：{filename}")
    if Path(filename).suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValidationError(f"不支持的模板图片格式：{filename}")
    if (
        any(character in '<>:"/\\|?*' or ord(character) < 32 for character in filename)
        or filename.endswith((" ", "."))
    ):
        raise ValidationError(f"模板文件名不兼容 Windows：{filename}")
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update(f"COM{index}" for index in range(1, 10))
    reserved.update(f"LPT{index}" for index in range(1, 10))
    windows_base = filename.split(".", 1)[0].rstrip(" .").upper()
    if windows_base in reserved:
        raise ValidationError(f"模板文件名不兼容 Windows：{filename}")
    return filename


def _branch_lists(step: Step) -> Iterator[tuple[str, list[Any]]]:
    branches = step.params.get("branches")
    if not isinstance(branches, dict):
        return
    for key, raw_steps in branches.items():
        if isinstance(raw_steps, list):
            yield str(key), raw_steps


def iter_steps(source: Preset | Step | Iterable[Step]) -> Iterator[Step]:
    if isinstance(source, Preset):
        roots = source.steps
    elif isinstance(source, Step):
        roots = [source]
    else:
        roots = source
    for step in roots:
        yield step
        for _key, raw_steps in _branch_lists(step):
            for raw in raw_steps:
                if not isinstance(raw, dict):
                    continue
                branch_step = Step.from_dict(raw)
                yield from iter_steps(branch_step)


def _rewrite_nested_steps(step: Step, operation: Callable[[Step], None]) -> None:
    for _key, raw_steps in _branch_lists(step):
        for index, raw in enumerate(raw_steps):
            if not isinstance(raw, dict):
                continue
            branch_step = Step.from_dict(raw)
            operation(branch_step)
            _rewrite_nested_steps(branch_step, operation)
            raw_steps[index] = branch_step.to_dict()


def _collect_step_ids(
    steps: Iterable[Step], main_ids: set[str], known_ids: set[str]
) -> None:
    for step in steps:
        known_ids.add(step.id)
        main_ids.add(step.id)
        for _key, raw_steps in _branch_lists(step):
            for raw in raw_steps:
                if isinstance(raw, dict):
                    _collect_step_ids([Step.from_dict(raw)], set(), known_ids)


def _normalize_step_list(
    steps: list[Step],
    *,
    main_ids: set[str] | None = None,
    is_branch: bool = False,
) -> None:
    if main_ids is None:
        main_ids = set()
        _collect_step_ids(steps, main_ids, set())
    earlier_ids: set[str] = set()
    for step in steps:
        unique_dependencies: list[str] = []
        for dependency in step.depends_on:
            if dependency in earlier_ids and dependency not in unique_dependencies:
                unique_dependencies.append(dependency)
        step.depends_on = unique_dependencies

        return_target = step.params.get("return_to")
        if return_target is not None:
            valid = (
                return_target in earlier_ids or return_target in main_ids
                if is_branch
                else return_target in earlier_ids
            )
            if not valid:
                step.params.pop("return_to", None)

        for _key, raw_steps in _branch_lists(step):
            branch_steps = [Step.from_dict(raw) for raw in raw_steps if isinstance(raw, dict)]
            _normalize_step_list(branch_steps, main_ids=main_ids, is_branch=True)
            raw_steps[:] = [branch_step.to_dict() for branch_step in branch_steps]
        earlier_ids.add(step.id)


def normalize_dependencies(preset: Preset) -> None:
    _normalize_step_list(preset.steps)


def reorder_step_list(steps: list[Step], ordered_step_ids: list[str]) -> bool:
    current_ids = [step.id for step in steps]
    if ordered_step_ids == current_ids:
        return False
    if len(ordered_step_ids) != len(current_ids) or set(ordered_step_ids) != set(
        current_ids
    ):
        raise ValueError("步骤顺序与当前预设不一致")
    steps_by_id = {step.id: step for step in steps}
    steps[:] = [steps_by_id[step_id] for step_id in ordered_step_ids]
    _normalize_step_list(steps)
    return True


def reorder_steps(preset: Preset, ordered_step_ids: list[str]) -> bool:
    return reorder_step_list(preset.steps, ordered_step_ids)


def _step_dicts(raw_steps: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for raw_step in raw_steps:
        yield raw_step
        params = raw_step.get("params")
        branches = params.get("branches") if isinstance(params, dict) else None
        if not isinstance(branches, dict):
            continue
        for branch_steps in branches.values():
            if isinstance(branch_steps, list):
                nested = [item for item in branch_steps if isinstance(item, dict)]
                yield from _step_dicts(nested)


def _validate_raw_step_tree(
    raw_steps: Any,
    global_ids: set[str],
    *,
    strict_dependencies: bool,
    main_ids: set[str] | None = None,
    is_branch: bool = False,
) -> None:
    if not isinstance(raw_steps, list):
        raise ValidationError("步骤列表必须是数组")
    if main_ids is None:
        main_ids = set()
        for raw in raw_steps:
            if not isinstance(raw, dict):
                continue
            step_id = str(raw.get("id", "")).strip()
            if not step_id:
                continue
            main_ids.add(step_id)
            raw_branches = raw.get("params", {}).get("branches") if isinstance(raw.get("params"), dict) else None
            if isinstance(raw_branches, dict):
                for raw_branch_steps in raw_branches.values():
                    if isinstance(raw_branch_steps, list):
                        _validate_raw_step_tree(
                            raw_branch_steps,
                            set(),
                            strict_dependencies=False,
                            main_ids=set(),
                            is_branch=True,
                        )
    earlier_ids: set[str] = set()
    for raw_step in raw_steps:
        if not isinstance(raw_step, dict):
            raise ValidationError("步骤必须是对象")
        step_id = str(raw_step.get("id", "")).strip()
        if not step_id:
            raise ValidationError("步骤 ID 不能为空")
        if step_id in global_ids:
            raise ValidationError("包含重复的步骤 ID")
        global_ids.add(step_id)
        dependencies = raw_step.get("depends_on", [])
        if not isinstance(dependencies, list):
            raise ValidationError("步骤 depends_on 必须是数组")
        if strict_dependencies and any(str(dep) not in earlier_ids for dep in dependencies):
            name = str(raw_step.get("name", "未命名步骤"))
            raise ValidationError(f"步骤“{name}”包含无效的前置步骤")
        params = raw_step.get("params", {})
        if not isinstance(params, dict):
            raise ValidationError("步骤 params 必须是对象")
        if strict_dependencies and params.get("return_to") is not None:
            return_target = str(params["return_to"])
            if is_branch:
                valid = return_target in earlier_ids or return_target in main_ids
            else:
                valid = return_target in earlier_ids
            if not valid:
                name = str(raw_step.get("name", "未命名步骤"))
                raise ValidationError(f"步骤“{name}”的返回连接目标无效")
        branches = params.get("branches")
        if branches is not None:
            if not isinstance(branches, dict):
                raise ValidationError("步骤 branches 必须是对象")
            for raw_key, branch_steps in branches.items():
                key = str(raw_key)
                if not key.isdigit():
                    raise ValidationError("步骤分支序号无效")
                _validate_raw_step_tree(
                    branch_steps,
                    global_ids,
                    strict_dependencies=strict_dependencies,
                    main_ids=main_ids,
                    is_branch=True,
                )
        earlier_ids.add(step_id)


def validate_preset_structure(
    preset: Preset, *, strict_dependencies: bool = True
) -> None:
    _validate_raw_step_tree(
        preset.to_dict().get("steps"),
        set(),
        strict_dependencies=strict_dependencies,
    )


def _remap_sibling_dependencies(
    raw_steps: list[dict[str, Any]],
    id_remap: dict[str, str],
    *,
    strict: bool,
    preserve_external: bool,
) -> None:
    earlier_ids: set[str] = set()
    for raw_step in raw_steps:
        old_id = str(raw_step.get("id", ""))
        dependencies = raw_step.get("depends_on", [])
        if not isinstance(dependencies, list):
            raise ValidationError("步骤 depends_on 必须是数组")
        remapped: list[str] = []
        for raw_dependency in dependencies:
            dependency = str(raw_dependency)
            if dependency in earlier_ids:
                remapped.append(id_remap[dependency])
            elif preserve_external and dependency not in id_remap:
                remapped.append(dependency)
            elif strict:
                name = str(raw_step.get("name", "未命名步骤"))
                raise ValidationError(f"步骤“{name}”包含无效的前置步骤")
        raw_step["id"] = id_remap[old_id]
        raw_step["depends_on"] = list(dict.fromkeys(remapped))

        params = raw_step.get("params")
        if isinstance(params, dict) and params.get("return_to") is not None:
            return_target = str(params["return_to"])
            if return_target in id_remap:
                params["return_to"] = id_remap[return_target]
            elif strict:
                name = str(raw_step.get("name", "未命名步骤"))
                raise ValidationError(f"步骤“{name}”的返回连接目标无效")

        params = raw_step.get("params")
        branches = params.get("branches") if isinstance(params, dict) else None
        if isinstance(branches, dict):
            for branch_steps in branches.values():
                if not isinstance(branch_steps, list):
                    continue
                nested = [item for item in branch_steps if isinstance(item, dict)]
                _remap_sibling_dependencies(
                    nested,
                    id_remap,
                    strict=strict,
                    preserve_external=False,
                )
        earlier_ids.add(old_id)


def remap_preset_ids(
    preset: Preset,
    *,
    strict_dependencies: bool = True,
    id_factory: Callable[[], str] = new_id,
) -> dict[str, str]:
    raw_preset = preset.to_dict()
    raw_steps = raw_preset["steps"]
    _validate_raw_step_tree(
        raw_steps,
        set(),
        strict_dependencies=strict_dependencies,
    )
    all_steps = list(_step_dicts(raw_steps))
    old_ids = [str(raw_step.get("id", "")) for raw_step in all_steps]
    if any(not step_id for step_id in old_ids):
        raise ValidationError("步骤 ID 不能为空")
    if len(old_ids) != len(set(old_ids)):
        raise ValidationError("包含重复的步骤 ID")
    id_remap = {step_id: id_factory() for step_id in old_ids}
    _remap_sibling_dependencies(
        raw_steps,
        id_remap,
        strict=strict_dependencies,
        preserve_external=False,
    )
    remapped = Preset.from_dict(raw_preset)
    remapped.id = id_factory()
    preset.id = remapped.id
    preset.steps = remapped.steps
    return id_remap


def clone_preset(
    preset: Preset,
    *,
    name: str | None = None,
    id_factory: Callable[[], str] = new_id,
) -> Preset:
    clone = Preset.from_dict(deepcopy(preset.to_dict()))
    remap_preset_ids(clone, id_factory=id_factory)
    if name is not None:
        clone.name = name
    return clone


def clone_step(
    step: Step,
    *,
    name: str | None = None,
    id_factory: Callable[[], str] = new_id,
) -> Step:
    raw_step = deepcopy(step.to_dict())
    _validate_raw_step_tree(
        [raw_step],
        set(),
        strict_dependencies=False,
    )
    all_steps = list(_step_dicts([raw_step]))
    old_ids = [str(item.get("id", "")) for item in all_steps]
    if len(old_ids) != len(set(old_ids)):
        raise ValidationError("包含重复的步骤 ID")
    id_remap = {step_id: id_factory() for step_id in old_ids}
    external_dependencies = list(step.depends_on)
    _remap_sibling_dependencies(
        [raw_step],
        id_remap,
        strict=False,
        preserve_external=True,
    )
    raw_step["depends_on"] = external_dependencies
    clone = Step.from_dict(raw_step)
    if name is not None:
        clone.name = name
    return clone


def run_preset_references(
    presets: Iterable[Preset], target_preset_id: str
) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    for owner in presets:
        for step in iter_steps(owner):
            if step.kind != "run_preset":
                continue
            if str(step.params.get("preset_id", "")) != target_preset_id:
                continue
            references.append(
                {
                    "preset_id": owner.id,
                    "preset_name": owner.name,
                    "step_id": step.id,
                    "step_name": step.name,
                }
            )
    return references


def template_references(
    presets: Iterable[Preset], filename: str
) -> list[dict[str, str]]:
    target = filename.casefold()
    references: list[dict[str, str]] = []
    for owner in presets:
        for step in iter_steps(owner):
            templates = step.params.get("templates", [])
            if not isinstance(templates, list):
                continue
            if not any(
                isinstance(item, dict)
                and str(item.get("file", "")).casefold() == target
                for item in templates
            ):
                continue
            references.append(
                {
                    "preset_id": owner.id,
                    "preset_name": owner.name,
                    "step_id": step.id,
                    "step_name": step.name,
                }
            )
    return references


def update_template_reference_resolutions(
    presets: Iterable[Preset], filename: str, resolution: tuple[int, int]
) -> int:
    target = filename.casefold()
    width, height = resolution
    updated = 0

    def update_step(step: Step) -> None:
        nonlocal updated
        templates = step.params.get("templates", [])
        if isinstance(templates, list):
            for item in templates:
                if not isinstance(item, dict):
                    continue
                if str(item.get("file", "")).casefold() != target:
                    continue
                item["screen_resolution"] = {"width": width, "height": height}
                updated += 1

    for preset in presets:
        for step in preset.steps:
            update_step(step)
            _rewrite_nested_steps(step, update_step)
    return updated


def unique_name(preferred: str, existing_names: Iterable[str]) -> str:
    existing = set(existing_names)
    if preferred not in existing:
        return preferred
    index = 2
    while f"{preferred} {index}" in existing:
        index += 1
    return f"{preferred} {index}"


def duplicate_preset_name(source_name: str, existing_names: Iterable[str]) -> str:
    return unique_name(f"{source_name} 副本", existing_names)


def imported_preset_name(source_name: str, existing_names: Iterable[str]) -> str:
    existing = set(existing_names)
    if source_name not in existing:
        return source_name
    return unique_name(f"{source_name} 导入", existing)


def _registry_or_default(registry: StepRegistry | None) -> StepRegistry:
    if registry is not None:
        return registry
    from .steps import REGISTRY

    return REGISTRY


def _positive_resolution(raw: Any, label: str) -> tuple[int, int] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValidationError(f"{label}屏幕分辨率必须是对象")
    try:
        width = int(raw.get("width", 0))
        height = int(raw.get("height", 0))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label}屏幕分辨率无效") from exc
    if width <= 0 or height <= 0:
        raise ValidationError(f"{label}屏幕分辨率必须大于 0")
    return width, height


def _validate_templates(params: dict[str, Any], step_name: str) -> None:
    templates = params.get("templates")
    if not isinstance(templates, list) or not templates:
        raise ValidationError(f"识别步骤“{step_name}”至少需要一个模板")
    for item in templates:
        if not isinstance(item, dict):
            raise ValidationError(f"识别步骤“{step_name}”的模板记录无效")
        try:
            threshold = float(item.get("threshold", 0.8))
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"识别步骤“{step_name}”的模板阈值无效") from exc
        if not 0.0 <= threshold <= 1.0:
            raise ValidationError(f"识别步骤“{step_name}”的模板阈值必须在 0 到 1 之间")
        item["file"] = validate_template_filename(str(item.get("file", "")))
        item["threshold"] = threshold
        _positive_resolution(item.get("screen_resolution"), "模板")


def _parse_step_list(
    raw_steps: Any,
    *,
    registry: StepRegistry,
    global_ids: set[str],
    normalize: bool,
    main_ids: set[str] | None = None,
    is_branch: bool = False,
) -> list[Step]:
    if not isinstance(raw_steps, list):
        raise ValidationError("步骤列表必须是数组")
    if main_ids is None:
        main_ids = {
            str(raw.get("id", "")).strip()
            for raw in raw_steps
            if isinstance(raw, dict) and str(raw.get("id", "")).strip()
        }
    parsed: list[Step] = []
    sibling_ids = {
        str(raw.get("id", "")).strip()
        for raw in raw_steps
        if isinstance(raw, dict)
    }
    earlier_ids: set[str] = set()
    for raw in raw_steps:
        if not isinstance(raw, dict):
            raise ValidationError("步骤必须是对象")
        step_id = str(raw.get("id", "")).strip()
        if not step_id:
            raise ValidationError("步骤 ID 不能为空")
        if step_id in global_ids:
            raise ValidationError(f"重复的步骤 ID {step_id}")
        global_ids.add(step_id)

        name = str(raw.get("name", "")).strip()
        if not name:
            raise ValidationError("步骤名称不能为空")
        raw_params = raw.get("params", {})
        migration_params = raw_params if isinstance(raw_params, dict) else {}
        kind = canonical_step_kind(str(raw.get("kind", "")).strip(), migration_params)
        definition = registry.get(kind)
        if definition is None:
            raise ValidationError(f"不支持的步骤类型：{kind}")
        if not isinstance(raw.get("enabled", True), bool):
            raise ValidationError(f"步骤“{name}”的 enabled 必须是布尔值")
        on_failure = raw.get("on_failure", "stop")
        if on_failure not in {"stop", "continue"}:
            raise ValidationError(f"步骤“{name}”的失败处理方式无效")
        if on_failure == "continue" and not definition.can_fail:
            raise ValidationError(f"步骤“{name}”不支持失败后继续")

        raw_dependencies = raw.get("depends_on", [])
        if not isinstance(raw_dependencies, list):
            raise ValidationError(f"步骤“{name}”的 depends_on 必须是数组")
        dependencies: list[str] = []
        for item in raw_dependencies:
            dependency = str(item).strip()
            if not dependency:
                if normalize:
                    continue
                raise ValidationError(f"步骤“{name}”包含空的前置步骤 ID")
            if dependency not in earlier_ids:
                if dependency in sibling_ids:
                    if normalize:
                        continue
                    raise ValidationError(f"步骤“{name}”包含无效的前置步骤")
                if dependency in global_ids:
                    raise ValidationError(f"步骤“{name}”包含跨层级的前置步骤")
                if normalize:
                    continue
                raise ValidationError(f"步骤“{name}”包含无效的前置步骤")
            if dependency not in dependencies:
                dependencies.append(dependency)

        params = raw_params
        if not isinstance(params, dict):
            raise ValidationError(f"步骤“{name}”的 params 必须是对象")
        params = deepcopy(params)
        branches = params.get("branches")
        if branches is not None:
            if kind != "find_and_tap":
                raise ValidationError(f"步骤“{name}”不支持分支")
            if not isinstance(branches, dict):
                raise ValidationError(f"步骤“{name}”的 branches 必须是对象")
            parsed_branches: dict[str, list[dict[str, Any]]] = {}
            for raw_key, branch_steps in branches.items():
                key = str(raw_key)
                if not key.isdigit() or int(key) < 0:
                    raise ValidationError(f"步骤“{name}”的分支序号无效")
                parsed_branch = _parse_step_list(
                    branch_steps,
                    registry=registry,
                    global_ids=global_ids,
                    normalize=normalize,
                    main_ids=main_ids,
                    is_branch=True,
                )
                parsed_branches[key] = [step.to_dict() for step in parsed_branch]
            params["branches"] = parsed_branches

        if kind == "find_and_tap":
            _validate_templates(params, name)
            tap_mode = params.get("tap_mode", "single")
            if tap_mode not in {"single", "multi"}:
                raise ValidationError(f"识别步骤“{name}”的识别后操作方式无效")
            template_count = len(params["templates"])
            for key in (params.get("branches") or {}):
                if int(key) >= template_count:
                    raise ValidationError(f"步骤“{name}”的分支序号超出模板范围")

        return_target = params.get("return_to")
        if return_target is not None:
            return_target = str(return_target).strip()
            valid = (
                not return_target
                or return_target == step_id
                or (return_target not in earlier_ids and not (is_branch and return_target in main_ids))
            )
            if valid:
                if normalize:
                    params.pop("return_to", None)
                else:
                    raise ValidationError(f"步骤“{name}”的返回连接目标无效")
            else:
                params["return_to"] = return_target

        resolution = _positive_resolution(raw.get("screen_resolution"), "步骤")
        step = Step(
            id=step_id,
            name=name,
            kind=kind,
            params=params,
            enabled=raw.get("enabled", True),
            on_failure=on_failure,
            depends_on=dependencies,
            screen_resolution=resolution,
        )
        parsed.append(step)
        earlier_ids.add(step_id)
    return parsed


def config_from_payload(
    payload: Any,
    *,
    registry: StepRegistry | None = None,
    normalize_dependencies: bool = True,
) -> AppConfig:
    if not isinstance(payload, dict):
        raise ValidationError("配置顶层内容必须是对象")
    raw_version = payload.get("version", 2)
    if isinstance(raw_version, bool) or (
        isinstance(raw_version, float) and not raw_version.is_integer()
    ):
        raise ValidationError("配置版本无效")
    try:
        version = int(raw_version)
    except (TypeError, ValueError) as exc:
        raise ValidationError("配置版本无效") from exc
    if version != 2:
        raise ValidationError(f"仅支持配置版本 2，收到版本 {version}")
    raw_presets = payload.get("presets")
    if not isinstance(raw_presets, list) or not raw_presets:
        raise ValidationError("配置中至少需要一个预设")
    acceleration = str(payload.get("acceleration", "cpu"))
    if acceleration not in {"cpu", "gpu"}:
        raise ValidationError("不支持的加速模式")

    active_registry = _registry_or_default(registry)
    global_step_ids: set[str] = set()
    preset_ids: set[str] = set()
    preset_names: set[str] = set()
    presets: list[Preset] = []
    for raw_preset in raw_presets:
        if not isinstance(raw_preset, dict):
            raise ValidationError("预设必须是对象")
        preset_id = str(raw_preset.get("id", "")).strip()
        if not preset_id:
            raise ValidationError("预设 ID 不能为空")
        if preset_id in preset_ids:
            raise ValidationError(f"重复的预设 ID {preset_id}")
        preset_ids.add(preset_id)
        name = str(raw_preset.get("name", "")).strip()
        if not name:
            raise ValidationError("预设名称不能为空")
        if name in preset_names:
            raise ValidationError(f"重复的预设名称 {name}")
        preset_names.add(name)
        loop_count = raw_preset.get("loop_count", 1)
        if isinstance(loop_count, bool) or (
            isinstance(loop_count, float) and not loop_count.is_integer()
        ):
            raise ValidationError(f"预设“{name}”的循环次数必须是非负整数")
        try:
            loop_count = int(loop_count)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"预设“{name}”的循环次数必须是非负整数") from exc
        if loop_count < 0:
            raise ValidationError(f"预设“{name}”的循环次数不能为负数")
        steps = _parse_step_list(
            raw_preset.get("steps", []),
            registry=active_registry,
            global_ids=global_step_ids,
            normalize=normalize_dependencies,
        )
        presets.append(Preset(id=preset_id, name=name, loop_count=loop_count, steps=steps))

    for preset in presets:
        for step in iter_steps(preset):
            if step.kind != "run_preset":
                continue
            target_id = str(step.params.get("preset_id", "")).strip()
            if not target_id or target_id not in preset_ids:
                raise ValidationError(f"步骤“{step.name}”引用了不存在的预设")

    selected = str(payload.get("selected_preset_id", "")).strip()
    if selected not in preset_ids:
        selected = presets[0].id
    return AppConfig(
        version=2,
        presets=presets,
        selected_preset_id=selected,
        acceleration=acceleration,
    )


def validate_config(
    config: AppConfig,
    *,
    registry: StepRegistry | None = None,
    normalize_dependencies: bool = False,
) -> None:
    config_from_payload(
        config.to_dict(),
        registry=registry,
        normalize_dependencies=normalize_dependencies,
    )
