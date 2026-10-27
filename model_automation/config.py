from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile
from threading import Lock, RLock
from typing import Any

from .models import AppConfig, Preset, Step
from .operations import ValidationError, config_from_payload, validate_config


if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"
TEMPLATE_DIR = PROJECT_ROOT / "templates_file"
SCHEMA_VERSION = 2


class ConfigError(RuntimeError):
    pass


def legacy_fgo_preset(
    support_pos: list[int] | tuple[int, int] = (300, 500),
    start_pos: list[int] | tuple[int, int] = (900, 1900),
) -> Preset:
    support_x, support_y = map(int, support_pos)
    start_x, start_y = map(int, start_pos)
    return Preset(
        name="默认刷本",
        steps=[
            Step(
                name="查找未完成副本",
                kind="find_and_tap",
                params={
                    "templates": [
                        {"file": "new.png", "threshold": 0.8},
                        {"file": "infinity_gray.png", "threshold": 0.85},
                        {"file": "arrow_gray.png", "threshold": 0.85},
                    ],
                    "attempts": 11,
                    "interval": 2.0,
                    "swipe_between": True,
                    "x1": 540,
                    "y1": 1800,
                    "x2": 540,
                    "y2": 800,
                    "duration": 300,
                    "tap_mode": "single",
                    "click_x": 540,
                    "click_y": 1000,
                    "wait_after": 0.0,
                },
            ),
            Step(name="等待助战界面", kind="wait", params={"seconds": 4.0}),
            Step(
                name="点击第一个助战",
                kind="tap",
                params={"x": support_x, "y": support_y, "wait_after": 1.0},
            ),
            Step(
                name="关闭可能的弹窗",
                kind="tap",
                params={"x": 540, "y": 1000, "wait_after": 3.0},
            ),
            Step(
                name="开始任务",
                kind="tap",
                params={"x": start_x, "y": start_y, "wait_after": 0.0},
            ),
        ],
    )


def default_config() -> AppConfig:
    preset = Preset(name="默认预设")
    return AppConfig(presets=[preset], selected_preset_id=preset.id)


class ConfigStore:
    # Stores pointing at the same path must also serialize initialization/migration.
    _locks_guard = Lock()
    _path_locks: dict[str, RLock] = {}

    def __init__(
        self,
        path: Path = CONFIG_PATH,
        template_dir: Path = TEMPLATE_DIR,
    ) -> None:
        self.path = path
        self.template_dir = template_dir
        key = os.path.normcase(str(path.resolve()))
        with self._locks_guard:
            self._lock = self._path_locks.setdefault(key, RLock())

    def load(self) -> AppConfig:
        with self._lock:
            return self._load()

    def _load(self) -> AppConfig:
        self.template_dir.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            config = default_config()
            self.save(config)
            return config

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"无法读取配置 {self.path.name}: {exc}") from exc

        if not isinstance(data, dict):
            raise ConfigError("配置内容无效: 顶层内容必须是对象")
        try:
            version = int(data.get("version", 1))
            if version > SCHEMA_VERSION:
                raise ConfigError(
                    f"配置版本 {version} 高于当前支持的版本 {SCHEMA_VERSION}"
                )
            if version < SCHEMA_VERSION:
                config = self._migrate_legacy(data)
                self.save(config)
                return config
            return config_from_payload(data, normalize_dependencies=False)
        except ConfigError:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise ConfigError(f"配置内容无效: {exc}") from exc

    def save(self, config: AppConfig) -> None:
        with self._lock:
            temporary: Path | None = None
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                payload = json.dumps(
                    config.to_dict(), ensure_ascii=False, indent=2, sort_keys=False
                )
                with NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=self.path.parent,
                    prefix=self.path.name + ".", suffix=".tmp", delete=False,
                ) as stream:
                    temporary = Path(stream.name)
                    stream.write(payload + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                temporary.replace(self.path)
            except OSError as exc:
                raise ConfigError(f"无法保存配置 {self.path.name}: {exc}") from exc
            finally:
                if temporary is not None:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass

    @staticmethod
    def _migrate_legacy(data: dict[str, Any]) -> AppConfig:
        support = data.get("support_pos", [300, 500])
        start = data.get("start_pos", [900, 1900])
        if not isinstance(support, (list, tuple)) or len(support) != 2:
            support = [300, 500]
        if not isinstance(start, (list, tuple)) or len(start) != 2:
            start = [900, 1900]
        preset = legacy_fgo_preset(support, start)
        return AppConfig(presets=[preset], selected_preset_id=preset.id)

    @staticmethod
    def _validate(config: AppConfig) -> None:
        try:
            validate_config(config)
        except ValidationError as exc:
            raise ConfigError(f"配置内容无效: {exc}") from exc
