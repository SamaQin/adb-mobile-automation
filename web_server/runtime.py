from __future__ import annotations

import asyncio
from collections import deque
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
import re
from threading import Event, RLock, Thread
from typing import Any, Callable
from uuid import uuid4

from model_automation.config import ConfigStore
from model_automation.device import DeviceError
from model_automation.engine import ExecutionReport, RuntimeContext, StepEngine
from model_automation.models import Preset, Step
from model_automation.registry import StepRegistry
from model_automation.steps import REGISTRY
from model_automation.vision import ACCELERATION_LABELS, get_acceleration, set_acceleration


class RuntimeConflict(RuntimeError):
    pass


@dataclass
class _Subscriber:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[dict[str, Any]]
    closed: asyncio.Event = field(default_factory=asyncio.Event)
    pending: deque[dict[str, Any]] = field(default_factory=deque)
    scheduled: bool = False
    overflow: bool = False


@dataclass
class _ExecutionFrame:
    preset: Preset
    active_steps: list[Step]
    preset_id: str | None
    cycle: int = 1
    current_step: Step | None = None
    current_index: int = 0


class _LogParser:
    START_RE = re.compile(r"^开始执行预设：(.*)（(\d+) 个步骤，循环 .+）$")
    STEP_RE = re.compile(r"^\[(\d+)/(\d+)] (.*)$")
    CYCLE_RE = re.compile(r"^第 (\d+)(?:/\d+)? 轮（已重置步骤状态）$")

    def __init__(self, presets: dict[str, Preset], root: Preset) -> None:
        self.presets = presets
        self.root = root
        self.frames: list[_ExecutionFrame] = []
        self.by_name: dict[str, Preset] = {preset.name: preset for preset in presets.values()}

    @staticmethod
    def _active_steps(preset: Preset) -> list[Step]:
        return [step for step in preset.steps if step.enabled]

    def _branch_preset(self, name: str) -> Preset | None:
        if not name.startswith("分支：") or not self.frames:
            return None
        label = name.removeprefix("分支：")
        parent = self.frames[-1].current_step
        if parent is None:
            return None
        templates = parent.params.get("templates", [])
        branches = parent.params.get("branches", {})
        if not isinstance(templates, list) or not isinstance(branches, dict):
            return None
        for index, item in enumerate(templates):
            if not isinstance(item, dict) or str(item.get("file", "")) != label:
                continue
            raw_steps = branches.get(str(index), [])
            if not isinstance(raw_steps, list):
                return None
            steps = [Step.from_dict(raw) for raw in raw_steps if isinstance(raw, dict)]
            return Preset(name=name, steps=steps, loop_count=1)
        return None

    def _start_frame(self, name: str) -> _ExecutionFrame:
        if not self.frames:
            preset = self.root
            preset_id: str | None = self.root.id
        else:
            branch = self._branch_preset(name)
            preset = branch or self.by_name.get(name) or Preset(name=name)
            preset_id = None if branch is not None else preset.id
        frame = _ExecutionFrame(
            preset=preset,
            active_steps=self._active_steps(preset),
            preset_id=preset_id,
        )
        self.frames.append(frame)
        return frame

    @staticmethod
    def _status_event(frame: _ExecutionFrame) -> dict[str, Any]:
        return {
            "type": "status",
            "data": {
                "state": "running",
                "preset_id": frame.preset_id,
                "cycle": frame.cycle,
                "step_index": frame.current_index,
                "step_count": len(frame.active_steps),
                "step_id": frame.current_step.id if frame.current_step else None,
            },
        }

    def process(self, text: str) -> tuple[str | None, list[dict[str, Any]]]:
        events: list[dict[str, Any]] = []
        match = self.START_RE.match(text)
        if match:
            frame = self._start_frame(match.group(1))
            events.append(self._status_event(frame))
            return None, events

        frame = self.frames[-1] if self.frames else None
        if frame is None:
            return None, events

        match = self.CYCLE_RE.match(text)
        if match:
            frame.cycle = int(match.group(1))
            frame.current_step = None
            frame.current_index = 0
            events.append(self._status_event(frame))
            return None, events

        match = self.STEP_RE.match(text)
        if match:
            index = int(match.group(1))
            frame.current_index = index
            frame.current_step = (
                frame.active_steps[index - 1]
                if 0 < index <= len(frame.active_steps)
                else None
            )
            step_id = frame.current_step.id if frame.current_step else None
            if step_id is not None:
                events.append(
                    {"type": "step", "data": {"step_id": step_id, "state": "running"}}
                )
            events.append(self._status_event(frame))
            return step_id, events

        step_id = frame.current_step.id if frame.current_step else None
        if text.startswith("  完成：") and step_id:
            events.append({"type": "step", "data": {"step_id": step_id, "state": "done"}})
            frame.current_step = None
        elif text.startswith("  中止："):
            if step_id:
                events.append({"type": "step", "data": {"step_id": step_id, "state": "failed"}})
            self.frames.pop()
            if self.frames:
                events.append(self._status_event(self.frames[-1]))
        elif text.startswith("  跳过："):
            if step_id:
                state = "skipped"
            else:
                next_index = frame.current_index + 1
                skipped = (
                    frame.active_steps[next_index - 1]
                    if 0 < next_index <= len(frame.active_steps)
                    else None
                )
                step_id = skipped.id if skipped else None
                frame.current_index = next_index if skipped else frame.current_index
                state = "skipped"
            if step_id:
                events.append({"type": "step", "data": {"step_id": step_id, "state": state}})
            frame.current_step = None
        elif text in {"预设执行完成", "预设没有启用的步骤"}:
            if step_id:
                events.append({"type": "step", "data": {"step_id": step_id, "state": "done"}})
            self.frames.pop()
            if self.frames:
                events.append(self._status_event(self.frames[-1]))
        return step_id, events


class RuntimeManager:
    def __init__(
        self,
        config_store: ConfigStore,
        device: Any,
        *,
        registry: StepRegistry = REGISTRY,
        engine_factory: Callable[[StepRegistry], StepEngine] = StepEngine,
        event_limit: int = 200,
        subscriber_limit: int = 200,
    ) -> None:
        self.config_store = config_store
        self.device = device
        self.registry = registry
        self.engine_factory = engine_factory
        self._lock = RLock()
        self._mutation_lock = RLock()
        self._subscriber_limit = max(1, subscriber_limit)
        self._events: deque[dict[str, Any]] = deque(maxlen=event_limit)
        self._subscribers: list[_Subscriber] = []
        self._stop_event: Event | None = None
        self._worker: Thread | None = None
        self._server_id = uuid4().hex
        self._seq = 0
        self._run_id: str | None = None
        self._node_states: dict[str, dict[str, Any]] = {}
        self._frames: dict[str, dict[str, Any]] = {}
        self._root_cycle = 0
        self._structured = False
        self._status: dict[str, Any] = {
            "state": "idle",
            "preset_id": None,
            "cycle": 0,
            "step_index": 0,
            "step_count": 0,
            "step_id": None,
        }

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._status["state"] in {"starting", "running", "stopping"}

    def ensure_mutable(self) -> None:
        if self.is_running:
            raise RuntimeConflict("请先停止当前预设")

    @contextmanager
    def mutation(self):
        """Serialize a complete synchronous mutation with start admission."""
        with self._mutation_lock:
            self.ensure_mutable()
            yield

    def status(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy({**self._status, "server_id": self._server_id, "run_id": self._run_id, "seq": self._seq,
                             "node_states": self._node_states, "frames": list(self._frames.values()),
                             "root_cycle": self._root_cycle})

    def events(self) -> list[dict[str, Any]]:
        with self._lock:
            return deepcopy(list(self._events))

    def _drain_subscriber(self, subscriber: _Subscriber) -> None:
        with self._lock:
            subscriber.scheduled = False
            if subscriber not in self._subscribers:
                return
            if subscriber.overflow:
                self._subscribers.remove(subscriber)
                subscriber.pending.clear()
                subscriber.closed.set()
                return
            while subscriber.pending:
                if subscriber.queue.full():
                    self._subscribers.remove(subscriber)
                    subscriber.pending.clear()
                    subscriber.closed.set()
                    return
                subscriber.queue.put_nowait(subscriber.pending.popleft())

    def _publish(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._seq += 1
            event = dict(event)
            event.update(server_id=self._server_id, run_id=self._run_id, seq=self._seq)
            if event["type"] == "status":
                event["data"] = {**self._status, **event.get("data", {}),
                    "server_id": self._server_id, "run_id": self._run_id, "seq": self._seq,
                    "root_cycle": self._root_cycle, "frames": list(self._frames.values())}
            # Published envelopes are owned here and read-only for queue consumers.
            # Copy once before sharing with history and every subscriber.
            event = deepcopy(event)
            if event["type"] == "step":
                data = event["data"]
                data.setdefault("error", data.get("message", "") if data.get("state") in {"failed", "skipped"} else "")
                self._node_states[data["step_id"]] = deepcopy(data)
            self._events.append(event)
            for subscriber in list(self._subscribers):
                # Bound callbacks as well as the asyncio queue when its loop is busy.
                if len(subscriber.pending) >= self._subscriber_limit:
                    subscriber.overflow = True
                elif not subscriber.overflow:
                    subscriber.pending.append(event)
                if not subscriber.scheduled:
                    subscriber.scheduled = True
                    try:
                        subscriber.loop.call_soon_threadsafe(self._drain_subscriber, subscriber)
                    except RuntimeError:
                        self._subscribers.remove(subscriber)

    def publish_device(self, data: dict[str, Any]) -> None:
        self._publish({"type": "device", "data": data})

    async def subscribe(
        self,
    ) -> tuple[list[dict[str, Any]], asyncio.Queue[dict[str, Any]], _Subscriber]:
        """Return an editable replay snapshot and a read-only shared live queue."""
        subscriber = _Subscriber(asyncio.get_running_loop(), asyncio.Queue(maxsize=self._subscriber_limit))
        with self._lock:
            # Replay display data only; state always comes from the final snapshot.
            backlog = deepcopy([event for event in self._events
                                if event["type"] in {"log", "device"}])
            backlog.append({"type": "status", "server_id": self._server_id, "run_id": self._run_id,
                            "seq": self._seq, "data": self.status()})
            self._subscribers.append(subscriber)
        return backlog, subscriber.queue, subscriber

    def unsubscribe(self, subscriber: _Subscriber) -> None:
        with self._lock:
            if subscriber in self._subscribers:
                self._subscribers.remove(subscriber)
            subscriber.pending.clear()

    def _update_status(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._status.update(data)

    def _engine_event(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._structured = True
            data = deepcopy(event["data"])
            frame_id = data["frame_id"]
            kind = event["type"]
            if kind == "frame" and data["action"] == "enter":
                self._frames[frame_id] = {**data, "step_id": None, "step_index": 0}
            elif kind == "frame" and data["action"] == "exit":
                self._frames.pop(frame_id, None)
                for node in list(self._node_states.values()):
                    if node.get("frame_id") == frame_id and node.get("state") == "running":
                        self._publish({"type": "step", "data": {**node, "state": "idle"}})
            elif kind == "cycle":
                frame = self._frames.get(frame_id)
                if frame is not None:
                    frame.update(data, step_id=None, step_index=0)
                if data.get("parent_frame_id") is None:
                    self._root_cycle = data["cycle"]
                    self._node_states.clear()
                else:
                    self._node_states = {key: node for key, node in self._node_states.items()
                                         if node.get("frame_id") != frame_id}
            elif kind == "step":
                frame = self._frames.get(frame_id)
                if frame is not None and data["state"] != "skipped":
                    frame.update(step_id=data["step_id"], step_index=data.get("step_index", 0))
                self._publish({"type": "step", "data": data})
            if self._frames:
                frame = next(reversed(self._frames.values()))
                self._status.update({key: frame.get(key) for key in
                                     ("preset_id", "cycle", "step_id", "step_index", "step_count",
                                      "frame_id", "parent_frame_id")})
            else:
                self._status.update(frame_id=None, parent_frame_id=None, step_id=None,
                                    step_index=0)
            self._publish({"type": "status", "data": {"reset_frame_id": frame_id} if kind == "cycle" else {}})

    def _log(self, parser: _LogParser, text: str) -> None:
        with self._lock:
            if self._structured:
                step_id = self._status.get("step_id")
                parsed_events = []
            else:
                step_id, parsed_events = parser.process(text)
            self._publish({"type": "log", "data": {"text": text, "step_id": step_id}})
            for event in parsed_events:
                if event["type"] == "status":
                    if len(parser.frames) == 1:
                        cycle = event["data"]["cycle"]
                        if cycle != self._root_cycle:
                            self._node_states.clear()
                        self._root_cycle = cycle
                    self._update_status(event["data"])
                self._publish(event)

    def start(self, preset_id: str) -> dict[str, Any]:
        stop_event = Event()
        with self._mutation_lock, self._lock:
            if self._status["state"] in {"starting", "running", "stopping"}:
                raise RuntimeConflict("已有预设正在运行")
            self._run_id = uuid4().hex
            self._node_states.clear()
            self._frames.clear()
            self._root_cycle = 0
            self._structured = False
            self._events.clear()
            self._status = {
                "state": "starting",
                "preset_id": preset_id,
                "cycle": 0,
                "step_index": 0,
                "step_count": 0,
                "step_id": None,
            }
            self._stop_event = stop_event

        try:
            state = self.device.state()
            if state != "device":
                raise DeviceError(f"设备状态不可用：{state}")
            config = self.config_store.load()
            applied_acceleration = set_acceleration(config.acceleration)
            if applied_acceleration != config.acceleration:
                config.acceleration = applied_acceleration
                self.config_store.save(config)
            snapshots = deepcopy(config.presets)
            presets = {preset.id: preset for preset in snapshots}
            target = presets.get(preset_id)
            if target is None:
                raise ValueError("找不到要运行的预设")
        except Exception:
            with self._lock:
                self._status["state"] = "idle"
                self._stop_event = None
            raise

        parser = _LogParser(presets, target)
        with self._lock:
            self._status = {
                "state": "stopping" if stop_event.is_set() else "running",
                "preset_id": target.id,
                "cycle": 1,
                "step_index": 0,
                "step_count": len([step for step in target.steps if step.enabled]),
                "step_id": None,
            }

        self._publish({"type": "status", "data": {}})
        started_status = self.status()
        label = ACCELERATION_LABELS.get(get_acceleration(), get_acceleration())
        self._log(parser, f"加速模式：{label}")

        def worker() -> None:
            try:
                engine = self.engine_factory(self.registry)
                context = RuntimeContext(
                    device=self.device,
                    template_dir=self.config_store.template_dir,
                    stop_event=stop_event,
                    log=lambda text: self._log(parser, text),
                    engine=engine,
                    presets=presets,
                    preset_path=((target.id, target.name),),
                    event=self._engine_event,
                    run_id=self._run_id,
                )
                report = engine.run(target, context)
            except Exception as exc:
                report = ExecutionReport("failed", str(exc))
            with self._lock:
                self._frames.clear()
                parser.frames.clear()
                for node in self._node_states.values():
                    if node.get("state") == "running":
                        node["state"] = "idle"
                self._status = {
                    "state": "idle",
                    "preset_id": None,
                    "cycle": 0,
                    "step_index": 0,
                    "step_count": 0,
                    "step_id": None,
                    "last_status": report.status,
                    "last_message": report.message,
                }
                self._stop_event = None
                self._worker = None
                self._publish(
                    {
                        "type": "finished",
                        "data": {**self.status(), "status": report.status, "message": report.message},
                    }
                )

        thread = Thread(target=worker, name="automation-web-runtime", daemon=True)
        with self._lock:
            self._worker = thread
        thread.start()
        return started_status

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if self._status["state"] not in {"starting", "running", "stopping"}:
                raise RuntimeConflict("当前没有正在运行的预设")
            stop_event = self._stop_event
            self._status["state"] = "stopping"
            if stop_event is not None:
                stop_event.set()
            self._publish({"type": "status", "data": {}})
            return self.status()
