from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from functools import wraps
from typing import Any

from .engine import RuntimeContext, StepResult
from .models import Preset, Step
from .recorded_actions import action_end, recording_duration
from .registry import FieldSpec, StepDefinition, StepRegistry
from .vision import Match, find_template, load_template, to_gray


def load_image(path):
    """Compatibility hook for existing step loaders/mocks; templates use the cache."""
    return load_template(path, grayscale=True)


REGISTRY = StepRegistry()


def _number(params: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(params.get(key, default))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"参数“{key}”必须是数字") from exc


def _integer(params: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(params.get(key, default))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"参数“{key}”必须是整数") from exc


def _validated_runner(kind: str):
    def decorate(runner):
        @wraps(runner)
        def validated(step: Step, context: RuntimeContext) -> StepResult:
            try:
                params = deepcopy(step.params)
                if step.kind == "find_and_multi_tap":
                    params.setdefault("tap_mode", "multi")
                params = REGISTRY.get(kind).validate_params(params)
            except ValueError as exc:
                return StepResult(False, str(exc))
            return runner(replace(step, params=params), context)
        return validated
    return decorate


@_validated_runner("wait")
def run_wait(step: Step, context: RuntimeContext) -> StepResult:
    seconds = max(0.0, _number(step.params, "seconds", 1.0))
    if not context.wait(seconds):
        return StepResult(False, "执行已停止")
    return StepResult(True, f"等待 {seconds:g} 秒")


def run_end_loop(step: Step, context: RuntimeContext) -> StepResult:
    return StepResult(True, "结束本次循环", restart=True)


@_validated_runner("tap")
def run_tap(step: Step, context: RuntimeContext) -> StepResult:
    x = _integer(step.params, "x", 0)
    y = _integer(step.params, "y", 0)
    if context.stop_event.is_set():
        return StepResult(False, "执行已停止")
    context.device.tap(x, y)
    wait_after = max(0.0, _number(step.params, "wait_after", 0.0))
    if wait_after and not context.wait(wait_after):
        return StepResult(False, "执行已停止")
    return StepResult(True, f"点击 ({x}, {y})")


@_validated_runner("swipe")
def run_swipe(step: Step, context: RuntimeContext) -> StepResult:
    params = step.params
    x1 = _integer(params, "x1", 540)
    y1 = _integer(params, "y1", 1800)
    x2 = _integer(params, "x2", 540)
    y2 = _integer(params, "y2", 800)
    duration = max(0, _integer(params, "duration", 300))
    if context.stop_event.is_set():
        return StepResult(False, "执行已停止")
    context.device.swipe(x1, y1, x2, y2, duration)
    wait_after = max(0.0, _number(params, "wait_after", 0.0))
    if wait_after and not context.wait(wait_after):
        return StepResult(False, "执行已停止")
    return StepResult(True, f"从 ({x1}, {y1}) 滑动到 ({x2}, {y2})")


def _load_templates(
    step: Step, context: RuntimeContext
) -> list[tuple[int, str, float, Any]]:
    templates: list[tuple[int, str, float, Any]] = []
    raw_templates = step.params.get("templates", [])
    for original_index, item in enumerate(raw_templates if isinstance(raw_templates, list) else []):
        if not isinstance(item, dict):
            continue
        filename = str(item.get("file", "")).strip()
        if not filename:
            continue
        threshold = max(0.0, min(1.0, float(item.get("threshold", 0.8))))
        image = load_image(context.template_dir / filename)
        if image is None:
            if step.params.get("require_all", False):
                context.log(f"  全部匹配所需模板不可用：{filename}")
                return []
            context.log(f"  模板不可用，已忽略：{filename}")
            continue
        templates.append((original_index, filename, threshold, to_gray(image)))
    return templates


def _branch_steps(step: Step, template_index: int) -> list[Step]:
    branches = step.params.get("branches", {})
    if not isinstance(branches, dict):
        return []
    raw_steps = branches.get(str(template_index), [])
    if not isinstance(raw_steps, list):
        return []
    return [Step.from_dict(raw) for raw in raw_steps if isinstance(raw, dict)]


def _run_branch(
    branch: list[Step], label: str, context: RuntimeContext
) -> StepResult | None:
    if not any(step.enabled for step in branch):
        return None
    if context.engine is None:
        return StepResult(False, "运行环境不支持分支步骤")
    branch_preset = Preset(name=f"分支：{label}", steps=branch, loop_count=1)
    sub_context = replace(context, allow_external_jump=True)
    report = context.engine.run(branch_preset, sub_context)
    if report.jump_to:
        return StepResult(True, f"分支“{label}”执行完成", jump_to=report.jump_to)
    if report.status == "completed":
        return StepResult(True, f"分支“{label}”执行完成")
    if report.status == "stopped":
        return StepResult(False, "执行已停止")
    return StepResult(False, f"分支“{label}”执行失败：{report.message}")


def _run_recognition_taps(
    step: Step,
    context: RuntimeContext,
    click_count: int,
    click_interval: float,
) -> StepResult:
    if click_count < 1:
        return StepResult(False, "连击次数必须大于 0")
    templates = _load_templates(step, context)
    if not templates:
        return StepResult(False, "没有可用的模板图片")

    require_all = bool(step.params.get("require_all", False))
    attempts = max(0, _integer(step.params, "attempts", 1))
    interval = max(0.0, _number(step.params, "interval", 1.0))
    attempt = 0
    while True:
        attempt += 1
        if context.stop_event.is_set():
            return StepResult(False, "执行已停止")
        screen = context.device.screenshot()
        if context.stop_event.is_set():
            return StepResult(False, "执行已停止")
        search_screen = screen
        origin_x = origin_y = 0
        if step.params.get("roi_enabled", False):
            origin_x = step.params["search_x"]
            origin_y = step.params["search_y"]
            width = step.params["search_width"]
            height = step.params["search_height"]
            screen_height, screen_width = screen.shape[:2]
            # Device pixel bounds are [x, x + width) and [y, y + height).
            # Reject invalid bounds instead of silently changing the search region.
            if (origin_x + width > screen_width or origin_y + height > screen_height):
                return StepResult(False, "搜索区域 ROI 超出屏幕范围（使用原始设备像素）")
            search_screen = screen[origin_y:origin_y + height, origin_x:origin_x + width]
        screen_gray = to_gray(search_screen)
        matches: list[tuple[int, str, Match]] = []
        for template_index, filename, threshold, image in templates:
            if context.stop_event.is_set():
                return StepResult(False, "执行已停止")
            match = find_template(screen_gray, image, threshold)
            if match is not None:
                match = Match(match.x + origin_x, match.y + origin_y, match.score)
                matches.append((template_index, filename, match))
        if context.stop_event.is_set():
            return StepResult(False, "执行已停止")
        if matches and (not require_all or len(matches) >= len(templates)):
            _, filename, match = min(
                matches,
                key=lambda item: (item[2].y, item[2].x, item[0]),
            )
            branches_done: list[str] = []
            for template_index, branch_filename, _match in matches:
                branch = _branch_steps(step, template_index)
                if not branch:
                    continue
                branch_result = _run_branch(branch, branch_filename, context)
                if branch_result is None:
                    continue
                if not branch_result.success:
                    return branch_result
                if branch_result.jump_to:
                    return StepResult(
                        True,
                        f"匹配 {branch_filename}，分支执行后返回",
                        jump_to=branch_result.jump_to,
                    )
                branches_done.append(branch_filename)
            if branches_done:
                names = "、".join(branches_done)
                return StepResult(
                    True,
                    f"匹配 {names}，跳过步骤操作，直接执行分支后重新开始执行预设",
                    restart=True,
                )

            if bool(step.params.get("custom_click", False)):
                target_x = _integer(step.params, "click_x", 540)
                target_y = _integer(step.params, "click_y", 1000)
            else:
                target_x = match.x
                target_y = match.y
            target_x += _integer(step.params, "offset_x", 0)
            target_y += _integer(step.params, "offset_y", 0)
            screen_height, screen_width = screen.shape[:2]
            if not (0 <= target_x < screen_width and 0 <= target_y < screen_height):
                return StepResult(
                    False,
                    f"点击坐标 ({target_x}, {target_y}) 超出屏幕范围",
                )
            for click_index in range(click_count):
                if context.stop_event.is_set():
                    return StepResult(False, "执行已停止")
                context.device.tap(target_x, target_y)
                if click_index < click_count - 1 and not context.wait(click_interval):
                    return StepResult(False, "执行已停止")
            wait_after = max(0.0, _number(step.params, "wait_after", 0.0))
            if wait_after and not context.wait(wait_after):
                return StepResult(False, "执行已停止")
            action = "点击" if click_count == 1 else f"连击 {click_count} 次"
            return StepResult(
                True,
                f"匹配 {filename}，相似度 {match.score:.3f}，{action} ({target_x}, {target_y})",
            )

        if attempts and attempt >= attempts:
            break
        reason = "未识别到全部模板" if require_all else "未识别到目标"
        if attempts:
            context.log(f"  第 {attempt}/{attempts} 次{reason}")
        else:
            context.log(f"  第 {attempt} 次{reason}，继续重试")
        if bool(step.params.get("tap_between", False)):
            if context.stop_event.is_set():
                return StepResult(False, "执行已停止")
            context.device.tap(
                _integer(step.params, "tap_between_x", 540),
                _integer(step.params, "tap_between_y", 1000),
            )
        if bool(step.params.get("swipe_between", False)):
            if context.stop_event.is_set():
                return StepResult(False, "执行已停止")
            context.device.swipe(
                _integer(step.params, "x1", 540),
                _integer(step.params, "y1", 1800),
                _integer(step.params, "x2", 540),
                _integer(step.params, "y2", 800),
                max(0, _integer(step.params, "duration", 300)),
            )
        if not context.wait(interval):
            return StepResult(False, "执行已停止")

    return StepResult(False, f"尝试 {attempts} 次后仍未识别到目标")


@_validated_runner("find_and_tap")
def run_find_and_tap(step: Step, context: RuntimeContext) -> StepResult:
    mode = step.params.get("tap_mode")
    if mode is None and step.kind == "find_and_multi_tap":
        mode = "multi"
    if mode == "multi":
        click_count = _integer(step.params, "click_count", 2)
        click_interval = max(0.0, _number(step.params, "click_interval", 0.1))
        return _run_recognition_taps(step, context, click_count, click_interval)
    if mode not in {None, "single"}:
        return StepResult(False, "识别后操作方式无效")
    return _run_recognition_taps(step, context, 1, 0.0)


def run_find_and_multi_tap(step: Step, context: RuntimeContext) -> StepResult:
    params = deepcopy(step.params)
    params["tap_mode"] = "multi"
    return run_find_and_tap(replace(step, kind="find_and_tap", params=params), context)


@_validated_runner("recorded_actions")
def run_recorded_actions(step: Step, context: RuntimeContext) -> StepResult:
    actions = step.params.get("actions", [])
    if not actions:
        return StepResult(False, "尚未录制操作")
    previous_end = 0
    for action in actions:
        if context.stop_event.is_set():
            return StepResult(False, "执行已停止")
        wait_ms = max(0, int(action["at"]) - previous_end)
        if wait_ms and not context.wait(wait_ms / 1000):
            return StepResult(False, "执行已停止")
        if context.stop_event.is_set():
            return StepResult(False, "执行已停止")
        if action["type"] == "tap":
            context.device.tap(int(action["x"]), int(action["y"]))
        elif action["type"] == "swipe":
            context.device.swipe(
                int(action["x1"]), int(action["y1"]),
                int(action["x2"]), int(action["y2"]),
                int(action["duration"]),
            )
        else:
            return StepResult(False, f"未知动作类型：{action['type']}")
        previous_end = action_end(action)
    return StepResult(True, f"已回放 {len(actions)} 个操作")


@_validated_runner("run_preset")
def run_run_preset(step: Step, context: RuntimeContext) -> StepResult:
    preset_id = str(step.params.get("preset_id", "")).strip()
    display_name = str(step.params.get("preset_name", "")).strip()
    if not preset_id:
        return StepResult(False, "未指定要执行的预设")
    if context.presets is None:
        return StepResult(False, "运行环境未提供预设数据")
    target = context.presets.get(preset_id)
    if target is None:
        return StepResult(False, f"找不到预设：{display_name or preset_id}")
    if context.engine is None:
        return StepResult(False, "运行环境不支持预设步骤")
    if any(item[0] == target.id for item in context.preset_path):
        chain = " → ".join(item[1] for item in context.preset_path) + f" → {target.name}"
        return StepResult(False, f"预设循环引用：{chain}")
    context.log(f"  执行预设“{target.name}”（作为步骤）")
    sub_preset = replace(target, loop_count=1)
    sub_context = replace(
        context,
        preset_path=context.preset_path + ((target.id, target.name),),
        allow_external_jump=True,
    )
    report = context.engine.run(sub_preset, sub_context)
    if report.jump_to:
        return StepResult(True, f"预设“{target.name}”执行完成", jump_to=report.jump_to)
    if report.status == "completed":
        return StepResult(True, f"预设“{target.name}”执行完成")
    if report.status == "stopped":
        return StepResult(False, "执行已停止")
    return StepResult(False, f"预设“{target.name}”执行失败：{report.message}")


RECOGNITION_SEARCH_FIELDS = (
    FieldSpec("templates", "模板与阈值", "templates", []),
    FieldSpec("require_all", "匹配模式", "bool", False),
    FieldSpec("roi_enabled", "限定搜索区域（原始设备像素）", "bool", False),
    FieldSpec("search_x", "搜索左上角 X（含）", "int", 0, "x"),
    FieldSpec("search_y", "搜索左上角 Y（含）", "int", 0, "y"),
    FieldSpec("search_width", "搜索宽度（右边界不含）", "int", 0, "x"),
    FieldSpec("search_height", "搜索高度（下边界不含）", "int", 0, "y"),
    FieldSpec("attempts", "识别次数（0 无限重试）", "int", 1),
    FieldSpec("interval", "重试间隔（秒）", "float", 1.0),
    FieldSpec("tap_between", "重试前点击", "bool", False),
    FieldSpec("tap_between_x", "点击 X", "int", 540, "x"),
    FieldSpec("tap_between_y", "点击 Y", "int", 1000, "y"),
    FieldSpec("swipe_between", "重试前滑动", "bool", False),
    FieldSpec("x1", "滑动起点 X", "int", 540, "x"),
    FieldSpec("y1", "滑动起点 Y", "int", 1800, "y"),
    FieldSpec("x2", "滑动终点 X", "int", 540, "x"),
    FieldSpec("y2", "滑动终点 Y", "int", 800, "y"),
    FieldSpec("duration", "滑动时长（毫秒）", "int", 300),
)
RECOGNITION_TARGET_FIELDS = (
    FieldSpec("custom_click", "自定义点击", "bool", False),
    FieldSpec("click_x", "自定义点击 X", "int", 540, "x"),
    FieldSpec("click_y", "自定义点击 Y", "int", 1000, "y"),
)
RECOGNITION_OFFSET_FIELDS = (
    FieldSpec("offset_x", "点击偏移 X", "int", 0, "x", True),
    FieldSpec("offset_y", "点击偏移 Y", "int", 0, "y", True),
)

RECOGNITION_ACTION_FIELDS = (
    FieldSpec(
        "tap_mode",
        "识别后操作",
        "choice",
        "single",
        options=(("single", "点击"), ("multi", "连击")),
    ),
    FieldSpec("click_count", "连击次数", "int", 2, minimum=1),
    FieldSpec("click_interval", "连击间隔（秒）", "float", 0.1),
)


REGISTRY.register(
    StepDefinition(
        key="find_and_tap",
        label="识别模板并点击/连击",
        can_fail=True,
        fields=RECOGNITION_SEARCH_FIELDS
        + RECOGNITION_TARGET_FIELDS
        + RECOGNITION_OFFSET_FIELDS
        + RECOGNITION_ACTION_FIELDS
        + (
            FieldSpec("wait_after", "点击后等待（秒）", "float", 0.0),
        ),
        runner=run_find_and_tap,
    )
)
REGISTRY.register(
    StepDefinition(
        key="tap",
        label="点击坐标",
        fields=(
            FieldSpec("x", "X 坐标", "int", 540, "x"),
            FieldSpec("y", "Y 坐标", "int", 1000, "y"),
            FieldSpec("wait_after", "点击后等待（秒）", "float", 0.0),
        ),
        runner=run_tap,
    )
)
REGISTRY.register(
    StepDefinition(
        key="swipe",
        label="滑动",
        fields=(
            FieldSpec("x1", "起点 X", "int", 540, "x"),
            FieldSpec("y1", "起点 Y", "int", 1800, "y"),
            FieldSpec("x2", "终点 X", "int", 540, "x"),
            FieldSpec("y2", "终点 Y", "int", 800, "y"),
            FieldSpec("duration", "时长（毫秒）", "int", 300),
            FieldSpec("wait_after", "滑动后等待（秒）", "float", 0.0),
        ),
        runner=run_swipe,
    )
)
REGISTRY.register(
    StepDefinition(
        key="wait",
        label="等待",
        fields=(FieldSpec("seconds", "等待秒数", "float", 1.0),),
        runner=run_wait,
    )
)
REGISTRY.register(
    StepDefinition(
        key="end_loop",
        label="结束本次循环",
        fields=(),
        runner=run_end_loop,
    )
)
REGISTRY.register(
    StepDefinition(
        key="run_preset",
        label="执行预设",
        can_fail=True,
        fields=(FieldSpec("preset_id", "要执行的预设", "preset", ""),),
        runner=run_run_preset,
    )
)
REGISTRY.register(
    StepDefinition(
        key="recorded_actions",
        label="录制操作",
        fields=(FieldSpec("actions", "操作序列", "recording", []),),
        runner=run_recorded_actions,
    )
)


def step_definitions(registry: StepRegistry = REGISTRY) -> list[dict[str, Any]]:
    definitions: list[dict[str, Any]] = []
    for definition in registry.all():
        fields = []
        for field in definition.fields:
            serialized = {
                "key": field.key,
                "label": field.label,
                "kind": field.kind,
                "default": deepcopy(field.default),
            }
            if field.coordinate_axis is not None:
                serialized["coordinate_axis"] = field.coordinate_axis
            if field.coordinate_offset:
                serialized["coordinate_offset"] = True
            if field.options:
                serialized["options"] = [
                    {"value": value, "label": label}
                    for value, label in field.options
                ]
            fields.append(serialized)
        definitions.append(
            {
                "key": definition.key,
                "label": definition.label,
                "can_fail": definition.can_fail,
                "fields": fields,
            }
        )
    return definitions


def step_summary(step: Step) -> str:
    params = step.params
    if step.kind == "wait":
        return f"{params.get('seconds', 1)} 秒"
    if step.kind == "tap":
        return f"({params.get('x', 0)}, {params.get('y', 0)})"
    if step.kind == "swipe":
        return (
            f"({params.get('x1', 0)}, {params.get('y1', 0)}) → "
            f"({params.get('x2', 0)}, {params.get('y2', 0)})"
        )
    if step.kind == "run_preset":
        return str(params.get("preset_name", "") or "（未选择预设）")
    if step.kind == "recorded_actions":
        actions = params.get("actions", [])
        if not actions:
            return "尚未录制"
        return f"{len(actions)} 个操作 · {recording_duration(actions) / 1000:.1f} 秒"
    if step.kind == "find_and_tap":
        names = [
            str(item.get("file", ""))
            for item in params.get("templates", [])
            if isinstance(item, dict)
        ]
        parts = [", ".join(names) or "无模板"]
        parts.append("全部匹配" if params.get("require_all") else "任一匹配即可")
        if params.get("tap_mode") == "multi":
            parts.append(f"连击 {params.get('click_count', 2)} 次")
        else:
            try:
                attempts = int(params.get("attempts", 1))
            except (TypeError, ValueError):
                attempts = 1
            parts.append("无限重试" if attempts <= 0 else f"{attempts} 次")
        if params.get("custom_click"):
            parts.append(f"点击 ({params.get('click_x', 540)}, {params.get('click_y', 1000)})")
        else:
            parts.append("点击识别位置")
        if params.get("offset_x") or params.get("offset_y"):
            parts.append(f"偏移 ({params.get('offset_x', 0)}, {params.get('offset_y', 0)})")
        if params.get("return_to"):
            parts.append("返回连接")
        if params.get("tap_between"):
            parts.append(
                "重试前点击 "
                f"({params.get('tap_between_x', 0)}, {params.get('tap_between_y', 0)})"
            )
        if params.get("swipe_between"):
            parts.append("重试前滑动")
        branches = params.get("branches", {})
        if isinstance(branches, dict):
            branch_steps = sum(
                len(raw) for raw in branches.values() if isinstance(raw, list)
            )
            if branch_steps:
                parts.append(f"分支 {branch_steps} 步")
        return "；".join(parts)
    return ""
