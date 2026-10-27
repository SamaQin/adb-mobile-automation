from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from math import isfinite
from typing import Any, Callable, TYPE_CHECKING


def validate_number(value: Any, key: str, *, integer: bool = False,
                    minimum: float | None = None, maximum: float | None = None) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"参数“{key}”必须是{'整数' if integer else '数字'}")
    try:
        number = float(value)
        if not isfinite(number):
            raise ValueError
        if integer:
            if not number.is_integer():
                raise ValueError
            number = int(value) if isinstance(value, (int, str)) else int(number)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"参数“{key}”必须是有限{'整数' if integer else '数字'}") from exc
    if minimum is not None and number < minimum:
        raise ValueError(f"参数“{key}”不能小于 {minimum:g}")
    if maximum is not None and number > maximum:
        raise ValueError(f"参数“{key}”不能大于 {maximum:g}")
    return number

if TYPE_CHECKING:
    from .engine import RuntimeContext, StepResult
    from .models import Step


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: str
    default: Any
    coordinate_axis: str | None = None
    coordinate_offset: bool = False
    options: tuple[tuple[str, str], ...] = ()
    minimum: float | None = None
    maximum: float | None = None

    def validate(self, value: Any) -> Any:
        if self.kind in {"int", "float"}:
            minimum = self.minimum
            if minimum is None and not self.coordinate_offset:
                minimum = 0
            return validate_number(value, self.key, integer=self.kind == "int",
                                   minimum=minimum, maximum=self.maximum)
        if self.kind == "bool" and not isinstance(value, bool):
            raise ValueError(f"参数“{self.key}”必须是布尔值")
        if self.kind in {"choice", "preset"} and not isinstance(value, str):
            raise ValueError(f"参数“{self.key}”必须是字符串")
        if self.kind == "choice" and value not in {option[0] for option in self.options}:
            raise ValueError(f"参数“{self.key}”的选项无效")
        if self.kind == "templates":
            from .operations import _validate_templates
            holder = {"templates": deepcopy(value)}
            _validate_templates(holder, self.label)
            return holder["templates"]
        return value


@dataclass(frozen=True)
class StepDefinition:
    key: str
    label: str
    fields: tuple[FieldSpec, ...]
    runner: Callable[["Step", "RuntimeContext"], "StepResult"]
    can_fail: bool = False

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(params, dict):
            raise ValueError("步骤 params 必须是对象")
        validated = deepcopy(params)
        for field in self.fields:
            validated[field.key] = field.validate(validated.get(field.key, deepcopy(field.default)))
        if self.key == "find_and_tap" and validated.get("roi_enabled", False):
            if validated["search_width"] <= 0 or validated["search_height"] <= 0:
                raise ValueError("搜索区域 ROI 的宽度和高度必须大于 0（原始设备像素）")
        return validated


class StepRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, StepDefinition] = {}

    def register(self, definition: StepDefinition) -> None:
        if definition.key in self._definitions:
            raise ValueError(f"步骤类型已注册: {definition.key}")
        self._definitions[definition.key] = definition

    def get(self, key: str) -> StepDefinition | None:
        return self._definitions.get(key)

    def all(self) -> tuple[StepDefinition, ...]:
        return tuple(self._definitions.values())
