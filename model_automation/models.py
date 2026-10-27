from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


def new_id() -> str:
    return uuid4().hex


def canonical_step_kind(kind: str, params: dict[str, Any]) -> str:
    if kind == "find_and_multi_tap":
        params.setdefault("tap_mode", "multi")
        kind = "find_and_tap"
    if kind == "find_and_tap":
        params.setdefault("tap_mode", "single")
        params.setdefault("custom_click", False)
        params.setdefault("click_x", 540)
        params.setdefault("click_y", 1000)
        params.setdefault("offset_x", 0)
        params.setdefault("offset_y", 0)
    return kind


@dataclass
class Step:
    name: str
    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    on_failure: str = "stop"
    depends_on: list[str] = field(default_factory=list)
    screen_resolution: tuple[int, int] | None = None
    id: str = field(default_factory=new_id)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Step":
        raw_resolution = data.get("screen_resolution")
        screen_resolution = None
        if raw_resolution is not None:
            if not isinstance(raw_resolution, dict):
                raise ValueError("步骤屏幕分辨率必须是对象")
            width = int(raw_resolution.get("width", 0))
            height = int(raw_resolution.get("height", 0))
            if width <= 0 or height <= 0:
                raise ValueError("步骤屏幕分辨率必须大于 0")
            screen_resolution = (width, height)
        params = dict(data.get("params") or {})
        kind = canonical_step_kind(str(data.get("kind") or "wait"), params)
        return cls(
            id=str(data.get("id") or new_id()),
            name=str(data.get("name") or "未命名步骤"),
            kind=kind,
            enabled=bool(data.get("enabled", True)),
            on_failure=(
                "continue" if data.get("on_failure") == "continue" else "stop"
            ),
            depends_on=[
                str(item)
                for item in (data.get("depends_on") or [])
                if str(item).strip()
            ],
            params=params,
            screen_resolution=screen_resolution,
        )

    def to_dict(self) -> dict[str, Any]:
        data = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "enabled": self.enabled,
            "on_failure": self.on_failure,
            "depends_on": list(self.depends_on),
            "params": self.params,
        }
        if self.screen_resolution is not None:
            width, height = self.screen_resolution
            data["screen_resolution"] = {"width": width, "height": height}
        return data


@dataclass
class Preset:
    name: str
    steps: list[Step] = field(default_factory=list)
    loop_count: int = 1
    id: str = field(default_factory=new_id)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Preset":
        return cls(
            id=str(data.get("id") or new_id()),
            name=str(data.get("name") or "未命名预设"),
            steps=[Step.from_dict(step) for step in data.get("steps", [])],
            loop_count=max(0, int(data.get("loop_count", 1))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "loop_count": self.loop_count,
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass
class AppConfig:
    presets: list[Preset]
    selected_preset_id: str
    version: int = 2
    acceleration: str = "cpu"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        presets = [Preset.from_dict(item) for item in data.get("presets", [])]
        if not presets:
            raise ValueError("配置中至少需要一个预设")
        selected = str(data.get("selected_preset_id") or presets[0].id)
        if not any(preset.id == selected for preset in presets):
            selected = presets[0].id
        return cls(
            version=int(data.get("version", 2)),
            presets=presets,
            selected_preset_id=selected,
            acceleration=str(data.get("acceleration", "cpu")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "selected_preset_id": self.selected_preset_id,
            "presets": [preset.to_dict() for preset in self.presets],
            "acceleration": self.acceleration,
        }

    def selected_preset(self) -> Preset:
        for preset in self.presets:
            if preset.id == self.selected_preset_id:
                return preset
        self.selected_preset_id = self.presets[0].id
        return self.presets[0]
