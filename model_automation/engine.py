from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4
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
    jump_to: str | None = None


@dataclass
class RuntimeContext:
    device: Any
    template_dir: Path
    stop_event: Event
    log: Callable[[str], None]
    engine: "StepEngine | None" = None
    presets: "dict[str, Preset] | None" = None
    preset_path: "tuple[tuple[str, str], ...]" = ()
    allow_external_jump: bool = False
    event: Callable[[dict[str, Any]], None] | None = None
    run_id: str | None = None
    frame_id: str | None = None
    parent_frame_id: str | None = None
    step_id: str | None = None
    cycle: int = 0
    start_step_id: str | None = None

    def emit(self, event_type: str, **data: Any) -> None:
        if self.event is not None:
            self.event({"type": event_type, "data": {
                "run_id": self.run_id, "frame_id": self.frame_id,
                "parent_frame_id": self.parent_frame_id, "cycle": self.cycle,
                **data,
            }})

    def wait(self, seconds: float) -> bool:
        return not self.stop_event.wait(max(0.0, seconds))


@dataclass(frozen=True)
class ExecutionReport:
    status: str
    message: str
    jump_to: str | None = None


class StepEngine:
    def __init__(self, registry: StepRegistry) -> None:
        self.registry = registry

    def run(self, preset: Preset, context: RuntimeContext) -> ExecutionReport:
        # Each invocation owns a frame; replace preserves optional callbacks in children.
        parent_step_id = context.step_id
        start_step_id = context.start_step_id
        context = replace(context, run_id=context.run_id or uuid4().hex,
                          parent_frame_id=context.frame_id, frame_id=uuid4().hex,
                          step_id=None, cycle=0, start_step_id=None)
        context.emit("frame", action="enter", preset_id=preset.id,
                     parent_step_id=parent_step_id, step_count=sum(step.enabled for step in preset.steps))
        report = ExecutionReport("failed", "执行异常")
        try:
            report = self._run(preset, context, start_step_id)
            return report
        except Exception as exc:
            report = ExecutionReport("failed", str(exc))
            raise
        finally:
            context.emit("frame", action="exit", preset_id=preset.id,
                         status=report.status, message=report.message, jump_to=report.jump_to)

    def _run(
        self, preset: Preset, context: RuntimeContext, start_step_id: str | None = None
    ) -> ExecutionReport:
        active_steps = [step for step in preset.steps if step.enabled]
        start_index = 0
        assumed: set[str] = set()
        if start_step_id is not None:
            start_position = next(
                (index for index, step in enumerate(preset.steps)
                 if step.id == start_step_id),
                -1,
            )
            start_index = next(
                (index for index, step in enumerate(active_steps)
                 if step.id == start_step_id),
                -1,
            )
            if start_position < 0 or start_index < 0:
                message = "起始步骤不存在或已停用"
                context.log(f"  中止：{message}")
                return ExecutionReport("failed", message)
            # Include disabled steps before the entry point: they were skipped
            # by configuration, not failed in this run, and must not block the
            # explicitly chosen start.
            assumed = {step.id for step in preset.steps[:start_position]}
        # A partial run is exactly one suffix pass; repeating the suffix would
        # either duplicate work or never reach the beginning again.
        loop_count = 1 if start_step_id is not None else max(0, preset.loop_count)
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

        if start_step_id is not None:
            context.log(
                f"从步骤“{active_steps[start_index].name}”开始执行"
                f"（跳过前 {start_index} 个启用步骤，执行到末尾）"
            )

        cycle = 0
        while loop_count == 0 or cycle < loop_count:
            cycle += 1
            context.cycle = cycle
            context.step_id = None
            context.emit("cycle", preset_id=preset.id, step_count=len(active_steps))
            for disabled in preset.steps:
                if not disabled.enabled:
                    context.emit("step", preset_id=preset.id, step_id=disabled.id,
                                 state="skipped", message="disabled")
            skipped: set[str] = {step.id for step in preset.steps if not step.enabled}
            # Steps before the chosen entry point are treated as already
            # completed, including disabled ones, so dependencies never block
            # an explicitly requested start.
            skipped.difference_update(assumed)
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

            cursor = start_index
            while cursor < len(active_steps):
                if context.stop_event.is_set():
                    return ExecutionReport("stopped", "执行已停止")
                index = cursor + 1
                step = active_steps[cursor]
                context.step_id = step.id

                missing = [dep for dep in step.depends_on if dep in skipped]
                if missing:
                    skipped.add(step.id)
                    context.emit("step", preset_id=preset.id, step_id=step.id,
                                 step_index=index, state="skipped", message="dependency", depends_on=missing)
                    names = "、".join(id_to_name.get(dep, dep) for dep in missing)
                    context.log(f"  跳过：前置步骤未执行（{names}）")
                    cursor += 1
                    continue

                context.emit("step", preset_id=preset.id, step_id=step.id,
                             step_index=index, state="running")
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
                    context.emit("step", preset_id=preset.id, step_id=step.id,
                                 step_index=index, state="done", message=result.message)
                    skipped.discard(step.id)
                    if result.message:
                        context.log(f"  完成：{result.message}")
                    if result.restart:
                        if start_step_id is not None:
                            context.log("  后缀执行结束（从指定步骤开始，不再进入下一轮）")
                        else:
                            context.log("  本轮执行结束，开始下一轮循环")
                        break
                    jump_target = result.jump_to or step.params.get("return_to")
                    if jump_target:
                        propagated = result.jump_to is not None
                        target_cursor = next(
                            (
                                item_index
                                for item_index, item in enumerate(active_steps)
                                if item.id == jump_target
                            ),
                            None,
                        )
                        if target_cursor is not None:
                            if target_cursor < start_index:
                                context.log(
                                    "  忽略起点之前的返回目标"
                                    f"“{id_to_name.get(jump_target, jump_target)}”"
                                )
                            elif target_cursor < cursor or (
                                propagated and target_cursor == cursor
                            ):
                                context.log(
                                    f"  返回步骤“{id_to_name.get(jump_target, jump_target)}”"
                                )
                                context.emit("jump", preset_id=preset.id, step_id=step.id,
                                             target_step_id=jump_target, external=False)
                                cursor = target_cursor
                                continue
                        if target_cursor is None:
                            if context.allow_external_jump:
                                context.emit("jump", preset_id=preset.id, step_id=step.id,
                                             target_step_id=jump_target, external=True)
                                context.log(f"  请求跳转到外部步骤“{jump_target}”")
                                context.log("预设执行完成")
                                return ExecutionReport(
                                    "completed", "已请求跳转", jump_to=jump_target
                                )
                            context.log(f"  忽略无效的返回目标“{jump_target}”")
                    cursor += 1
                    continue

                reason = result.message or "步骤执行失败"
                context.emit("step", preset_id=preset.id, step_id=step.id,
                             step_index=index, state="skipped" if step.on_failure == "continue" else "failed",
                             message=reason)
                if step.on_failure == "continue":
                    skipped.add(step.id)
                    context.log(f"  跳过：{reason}")
                    cursor += 1
                    continue
                context.log(f"  中止：{reason}")
                return ExecutionReport("failed", f"步骤“{step.name}”失败：{reason}")

        context.log("预设执行完成")
        return ExecutionReport("completed", "预设执行完成")
