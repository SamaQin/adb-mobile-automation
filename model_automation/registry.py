from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TYPE_CHECKING

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


@dataclass(frozen=True)
class StepDefinition:
    key: str
    label: str
    fields: tuple[FieldSpec, ...]
    runner: Callable[["Step", "RuntimeContext"], "StepResult"]
    can_fail: bool = False


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
