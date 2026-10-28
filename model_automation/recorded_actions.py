from __future__ import annotations

from math import isfinite
from typing import Any


MAX_ACTIONS = 1000
MAX_GESTURE_MS = 5000


def _integer(value: Any, key: str, *, minimum: int = 0,
             maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"动作字段“{key}”必须是整数")
    try:
        number = float(value)
        if not isfinite(number) or not number.is_integer():
            raise ValueError
        result = int(value) if isinstance(value, (int, str)) else int(number)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"动作字段“{key}”必须是有限整数") from exc
    if result < minimum:
        raise ValueError(f"动作字段“{key}”不能小于 {minimum}")
    if maximum is not None and result > maximum:
        raise ValueError(f"动作字段“{key}”不能大于 {maximum}")
    return result


def normalize_actions(value: Any) -> list[dict[str, int | str]]:
    if not isinstance(value, list):
        raise ValueError("动作序列必须是数组")
    if len(value) > MAX_ACTIONS:
        raise ValueError(f"动作数量不能超过 {MAX_ACTIONS} 条")
    actions: list[dict[str, int | str]] = []
    previous_at = 0
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise ValueError(f"第 {index + 1} 条动作必须是对象")
        action_type = raw.get("type")
        if action_type not in {"tap", "swipe"}:
            raise ValueError(f"第 {index + 1} 条动作类型无效")
        at = _integer(raw.get("at"), "at")
        if index == 0 and at != 0:
            raise ValueError("第一条动作的时间必须为 0")
        if index > 0 and at < previous_at:
            raise ValueError("动作时间必须按顺序递增")
        if action_type == "tap":
            actions.append({
                "type": "tap",
                "x": _integer(raw.get("x"), "x"),
                "y": _integer(raw.get("y"), "y"),
                "at": at,
            })
        else:
            actions.append({
                "type": "swipe",
                "x1": _integer(raw.get("x1"), "x1"),
                "y1": _integer(raw.get("y1"), "y1"),
                "x2": _integer(raw.get("x2"), "x2"),
                "y2": _integer(raw.get("y2"), "y2"),
                "duration": _integer(raw.get("duration"), "duration",
                                     minimum=1, maximum=MAX_GESTURE_MS),
                "at": at,
            })
        previous_at = at
    return actions


def action_end(action: dict[str, Any]) -> int:
    at = int(action.get("at", 0))
    if action.get("type") == "swipe":
        return at + int(action.get("duration", 0))
    return at


def recording_duration(actions: list[dict[str, Any]]) -> int:
    if not actions:
        return 0
    return action_end(actions[-1])
