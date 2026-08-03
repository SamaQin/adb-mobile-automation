from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any, Callable

from .models import Preset
from .registry import StepRegistry


@dataclass(frozen=True)
class StepResult:
    success: bool
    message: str = ""
    restart: bool = False


@dataclass
class RuntimeContext:
    device: Any
    template_dir: Path
    stop_event: Event
    log: Callable[[str], None]
    engine: "StepEngine | None" = None
    presets: "dict[str, Preset] | None" = None
    preset_path: "tuple[tuple[str, str], ...]" = ()

    def wait(self, seconds: float) -> bool:
        return not self.stop_event.wait(max(0.0, seconds))


@dataclass(frozen=True)
class ExecutionReport:
    status: str
    message: str


class StepEngine:
    def __init__(self, registry: StepRegistry) -> None:
        self.registry = registry

    def run(self, preset: Preset, context: RuntimeContext) -> ExecutionReport:
        active_steps = [step for step in preset.steps if step.enabled]
        loop_count = max(0, preset.loop_count)
        loop_label = "无限" if loop_count == 0 else str(loop_count)
        context.log(
            f"开始执行预设：{preset.name}（{len(active_steps)} 个步骤，循环 {loop_label}）"
        )

        if not active_steps:
            if loop_count == 0:
                message = "无限循环预设没有启用的步骤"
                context.log(f"  中止：{message}")
                return ExecutionReport("failed", message)
            context.log("预设没有启用的步骤")
            return ExecutionReport("completed", "预设执行完成")

        cycle = 0
        while loop_count == 0 or cycle < loop_count:
            cycle += 1
            skipped: set[str] = {step.id for step in preset.steps if not step.enabled}
            known_ids = {step.id for step in preset.steps}
            for step in preset.steps:
                for dep in step.depends_on:
                    if dep not in known_ids:
                        skipped.add(dep)
            id_to_name = {step.id: step.name for step in preset.steps}

            if loop_count == 0:
                context.log(f"第 {cycle} 轮（已重置步骤状态）")
            elif loop_count > 1:
                context.log(f"第 {cycle}/{loop_count} 轮（已重置步骤状态）")

            for index, step in enumerate(active_steps, start=1):
                if context.stop_event.is_set():
                    return ExecutionReport("stopped", "执行已停止")

                missing = [dep for dep in step.depends_on if dep in skipped]
                if missing:
                    skipped.add(step.id)
                    names = "、".join(id_to_name.get(dep, dep) for dep in missing)
                    context.log(f"  跳过：前置步骤未执行（{names}）")
                    continue

                definition = self.registry.get(step.kind)
                if definition is None:
                    result = StepResult(False, f"未知步骤类型：{step.kind}")
                else:
                    context.log(f"[{index}/{len(active_steps)}] {step.name}")
                    try:
                        result = definition.runner(step, context)
                    except Exception as exc:
                        result = StepResult(False, str(exc))

                if context.stop_event.is_set():
                    return ExecutionReport("stopped", "执行已停止")
                if result.success:
                    if result.message:
                        context.log(f"  完成：{result.message}")
                    if result.restart:
                        context.log("  本轮执行结束，开始下一轮循环")
                        break
                    continue

                reason = result.message or "步骤执行失败"
                if step.on_failure == "continue":
                    skipped.add(step.id)
                    context.log(f"  跳过：{reason}")
                    continue
                context.log(f"  中止：{reason}")
                return ExecutionReport("failed", f"步骤“{step.name}”失败：{reason}")

        context.log("预设执行完成")
        return ExecutionReport("completed", "预设执行完成")
