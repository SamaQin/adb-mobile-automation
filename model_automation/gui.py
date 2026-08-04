from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from queue import Empty, Queue
import shutil
from threading import Event, Thread
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

from .config import ConfigError, ConfigStore, PROJECT_ROOT, TEMPLATE_DIR
from .device import AdbClient, DeviceError
from .engine import RuntimeContext, StepEngine
from .models import AppConfig, Preset, Step
from .operations import normalize_dependencies, reorder_steps
from .preset_archive import (
    PresetArchiveError,
    export_preset,
    import_preset,
)
from .registry import FieldSpec, StepDefinition
from .steps import REGISTRY, step_summary
from .vision import (
    ACCELERATION_CPU,
    ACCELERATION_LABELS,
    acceleration_backend,
    get_acceleration,
    save_image,
    select_point,
    select_region,
    select_swipe,
    set_acceleration,
)


FAILURE_LABELS = {
    "stop": "停止预设",
    "continue": "跳到下一步",
}


def image_window_bounds(widget: tk.Misc) -> tuple[int, int]:
    screen_width = widget.winfo_screenwidth()
    screen_height = widget.winfo_screenheight()
    return max(1, int(screen_width * 0.90)), max(1, int(screen_height * 0.82))


class StepDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        step: Step | None,
        adb: AdbClient,
        template_dir: Path,
        earlier_steps: list[Step],
        presets: list[Preset] | None = None,
    ) -> None:
        super().__init__(parent)
        self.title("编辑步骤" if step else "新增步骤")
        self.transient(parent)
        self.resizable(False, True)
        self.adb = adb
        self.template_dir = template_dir
        self.earlier_steps = earlier_steps
        self.presets = presets or []
        self.source = step
        self.result: Step | None = None
        self.field_vars: dict[str, tk.Variable] = {}
        self.template_tree: ttk.Treeview | None = None
        self.template_resolutions: dict[str, tuple[int, int] | None] = {}
        self.branch_steps: dict[str, list[Step]] = {}
        self.dep_list: tk.Listbox | None = None

        definitions = REGISTRY.all()
        self.definitions_by_label = {item.label: item for item in definitions}
        initial_definition = REGISTRY.get(step.kind) if step else definitions[0]
        if initial_definition is None:
            initial_definition = definitions[0]

        self.name_var = tk.StringVar(
            value=step.name if step else initial_definition.label
        )
        self.type_var = tk.StringVar(value=initial_definition.label)
        self.enabled_var = tk.BooleanVar(value=step.enabled if step else True)
        self.failure_var = tk.StringVar(
            value=FAILURE_LABELS.get(
                step.on_failure if step else "stop", FAILURE_LABELS["stop"]
            )
        )

        body = ttk.Frame(self, padding=16)
        body.grid(sticky="nsew")
        body.columnconfigure(1, weight=1)

        ttk.Label(body, text="步骤名称").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(body, textvariable=self.name_var, width=42).grid(
            row=0, column=1, sticky="ew", pady=4
        )

        ttk.Label(body, text="步骤类型").grid(row=1, column=0, sticky="w", pady=4)
        type_box = ttk.Combobox(
            body,
            textvariable=self.type_var,
            values=list(self.definitions_by_label),
            state="readonly",
            width=39,
        )
        type_box.grid(row=1, column=1, sticky="ew", pady=4)
        type_box.bind("<<ComboboxSelected>>", self._change_type)

        ttk.Checkbutton(body, text="启用此步骤", variable=self.enabled_var).grid(
            row=2, column=1, sticky="w", pady=4
        )

        ttk.Label(body, text="执行失败时").grid(
            row=3, column=0, sticky="w", pady=4
        )
        self.failure_box = ttk.Combobox(
            body,
            textvariable=self.failure_var,
            values=list(FAILURE_LABELS.values()),
            state="readonly",
            width=39,
        )
        self.failure_box.grid(row=3, column=1, sticky="ew", pady=4)

        ttk.Label(body, text="关联前置步骤").grid(
            row=4, column=0, sticky="nw", pady=4
        )
        deps_frame = ttk.Frame(body)
        deps_frame.grid(row=4, column=1, sticky="ew", pady=4)
        self.dep_list = tk.Listbox(
            deps_frame,
            height=4,
            selectmode="multiple",
            exportselection=False,
            width=42,
        )
        self.dep_list.pack(fill="x")
        for index, earlier in enumerate(self.earlier_steps, start=1):
            self.dep_list.insert("end", f"{index}. {earlier.name}")
        pre_selected = set(step.depends_on if step else [])
        for index, earlier in enumerate(self.earlier_steps):
            if earlier.id in pre_selected:
                self.dep_list.selection_set(index)
        ttk.Label(
            deps_frame,
            text="仅可选顺序在前的步骤；前置步骤本轮未执行时，本步骤自动跳过。",
            foreground="#64748b",
            wraplength=360,
        ).pack(fill="x", pady=(3, 0))

        ttk.Separator(body).grid(row=5, column=0, columnspan=2, sticky="ew", pady=8)
        self.fields_frame = ttk.Frame(body)
        self.fields_frame.grid(row=6, column=0, columnspan=2, sticky="nsew")
        self.fields_frame.columnconfigure(1, weight=1)

        buttons = ttk.Frame(body)
        buttons.grid(row=7, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="保存", command=self._save).pack(
            side="right", padx=(0, 8)
        )

        self._build_fields(initial_definition, step.params if step else {})
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.grab_set()
        self.wait_visibility()
        self.focus_set()

    def _change_type(self, _event: tk.Event | None = None) -> None:
        definition = self.definitions_by_label[self.type_var.get()]
        self._build_fields(definition, {})

    def _build_fields(
        self, definition: StepDefinition, values: dict[str, Any]
    ) -> None:
        for child in self.fields_frame.winfo_children():
            child.destroy()
        self.field_vars.clear()
        self.template_tree = None
        self.template_resolutions.clear()
        self.branch_steps.clear()
        self.failure_box.configure(
            state="readonly" if definition.can_fail else "disabled"
        )
        if not definition.can_fail:
            self.failure_var.set(FAILURE_LABELS["stop"])

        row = 0
        for spec in definition.fields:
            value = values.get(spec.key, deepcopy(spec.default))
            if spec.kind == "templates":
                ttk.Label(self.fields_frame, text=spec.label).grid(
                    row=row, column=0, sticky="nw", pady=4
                )
                self._build_template_list(row, value, values)
                row += 1
                continue

            ttk.Label(self.fields_frame, text=spec.label).grid(
                row=row, column=0, sticky="w", pady=4
            )
            if spec.kind == "preset":
                preset_names = [preset.name for preset in self.presets]
                selected_name = str(values.get("preset_name", "") or "")
                for preset in self.presets:
                    if preset.id == str(value or ""):
                        selected_name = preset.name
                if selected_name not in preset_names:
                    selected_name = ""
                variable = tk.StringVar(value=selected_name)
                widget = ttk.Combobox(
                    self.fields_frame,
                    textvariable=variable,
                    values=preset_names,
                    state="readonly",
                    width=24,
                )
            elif spec.key == "require_all":
                variable = tk.StringVar(
                    value="全部模板匹配" if bool(value) else "任一模板匹配即可"
                )
                widget = ttk.Combobox(
                    self.fields_frame,
                    textvariable=variable,
                    values=["任一模板匹配即可", "全部模板匹配"],
                    state="readonly",
                    width=18,
                )
            elif spec.kind == "choice":
                choices = dict(spec.options)
                variable = tk.StringVar(value=choices.get(str(value), str(value)))
                widget = ttk.Combobox(
                    self.fields_frame,
                    textvariable=variable,
                    values=list(choices.values()),
                    state="readonly",
                    width=18,
                )
            elif spec.kind == "bool":
                variable: tk.Variable = tk.BooleanVar(value=bool(value))
                widget = ttk.Checkbutton(self.fields_frame, variable=variable)
            else:
                variable = tk.StringVar(value=str(value))
                widget = ttk.Entry(
                    self.fields_frame, textvariable=variable, width=24
                )
            widget.grid(row=row, column=1, sticky="ew", pady=4)
            self.field_vars[spec.key] = variable
            row += 1

        if definition.key == "tap":
            ttk.Button(
                self.fields_frame,
                text="从设备截图选点",
                command=self._pick_tap_position,
            ).grid(row=row, column=1, sticky="w", pady=(5, 0))
        elif definition.key == "swipe":
            ttk.Button(
                self.fields_frame,
                text="从设备截图拖动选择",
                command=self._pick_swipe_range,
            ).grid(row=row, column=1, sticky="w", pady=(5, 0))
        elif definition.key == "find_and_tap":
            retry_actions = ttk.Frame(self.fields_frame)
            retry_actions.grid(row=row, column=1, sticky="w", pady=(5, 0))
            ttk.Button(
                retry_actions,
                text="识别后点击选点",
                command=self._pick_recognition_target_position,
            ).pack(side="left")
            ttk.Button(
                retry_actions,
                text="重试前点击选点",
                command=self._pick_retry_tap_position,
            ).pack(side="left", padx=(6, 0))
            ttk.Button(
                retry_actions,
                text="重试前滑动选点",
                command=self._pick_retry_swipe_range,
            ).pack(side="left", padx=(6, 0))

    def _build_template_list(self, row: int, value: Any, params: dict[str, Any]) -> None:
        frame = ttk.Frame(self.fields_frame)
        frame.grid(row=row, column=1, sticky="ew", pady=4)
        tree = ttk.Treeview(
            frame,
            columns=("file", "threshold"),
            show="headings",
            height=4,
            selectmode="browse",
        )
        tree.heading("file", text="模板文件")
        tree.heading("threshold", text="阈值")
        tree.column("file", width=230, anchor="w")
        tree.column("threshold", width=70, anchor="center", stretch=False)
        tree.grid(row=0, column=0, columnspan=5, sticky="ew")
        frame.columnconfigure(0, weight=1)
        branches = params.get("branches", {})
        branch_map = branches if isinstance(branches, dict) else {}
        for index, item in enumerate(value if isinstance(value, list) else []):
            if isinstance(item, dict):
                item_id = tree.insert(
                    "",
                    "end",
                    values=(item.get("file", ""), item.get("threshold", 0.8)),
                )
                raw_branch = branch_map.get(str(index), [])
                self.branch_steps[item_id] = [
                    Step.from_dict(raw)
                    for raw in raw_branch
                    if isinstance(raw, dict)
                ] if isinstance(raw_branch, list) else []
                resolution = None
                raw_resolution = item.get("screen_resolution")
                if isinstance(raw_resolution, dict):
                    try:
                        width = int(raw_resolution.get("width", 0))
                        height = int(raw_resolution.get("height", 0))
                        if width > 0 and height > 0:
                            resolution = (width, height)
                    except (TypeError, ValueError):
                        pass
                if resolution is None and self.source is not None:
                    resolution = self.source.screen_resolution
                self.template_resolutions[item_id] = resolution
        ttk.Button(frame, text="添加已有", command=self._add_template).grid(
            row=1, column=0, sticky="w", pady=(5, 0)
        )
        ttk.Button(
            frame, text="设备截图", command=self._capture_step_template
        ).grid(row=1, column=1, pady=(5, 0), padx=5)
        ttk.Button(frame, text="修改阈值", command=self._edit_threshold).grid(
            row=1, column=2, pady=(5, 0), padx=(0, 5)
        )
        ttk.Button(frame, text="编辑分支", command=self._edit_branch).grid(
            row=1, column=3, pady=(5, 0), padx=(0, 5)
        )
        ttk.Button(frame, text="移除", command=self._remove_template).grid(
            row=1, column=4, sticky="e", pady=(5, 0)
        )
        self.template_tree = tree

    def _add_template(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="选择模板图片",
            initialdir=self.template_dir,
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp"), ("所有文件", "*.*")],
        )
        if not path or self.template_tree is None:
            return
        source = Path(path)
        if source.resolve().parent != self.template_dir.resolve():
            messagebox.showinfo(
                "尚未导入",
                "请先在“模板资源”页导入图片，再将其添加到步骤。",
                parent=self,
            )
            return
        threshold = simpledialog.askfloat(
            "识别阈值",
            "请输入 0 到 1 之间的阈值：",
            initialvalue=0.8,
            minvalue=0.0,
            maxvalue=1.0,
            parent=self,
        )
        if threshold is None:
            return
        self._set_template_reference(source.name, threshold)

    def _capture_step_template(self) -> None:
        if self.template_tree is None:
            return
        try:
            image = self.adb.screenshot()
            max_width, max_height = image_window_bounds(self)
            self.withdraw()
            region = select_region(
                "框选识别目标后按 Enter", image, max_width, max_height
            )
        except DeviceError as exc:
            messagebox.showerror("截图失败", str(exc), parent=self)
            return
        finally:
            self.deiconify()
        if region is None:
            return

        filename = simpledialog.askstring(
            "保存模板",
            "模板文件名：",
            initialvalue="template.png",
            parent=self,
        )
        if filename is None:
            return
        filename = Path(filename.strip()).name
        if not filename:
            return
        if Path(filename).suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp"}:
            filename += ".png"
        destination = self.template_dir / filename
        if destination.exists() and not messagebox.askyesno(
            "覆盖模板", f"{filename} 已存在，是否覆盖？", parent=self
        ):
            return
        threshold = simpledialog.askfloat(
            "识别阈值",
            "请输入 0 到 1 之间的阈值：",
            initialvalue=0.8,
            minvalue=0.0,
            maxvalue=1.0,
            parent=self,
        )
        if threshold is None:
            return

        x, y, width, height = region
        try:
            save_image(destination, image[y : y + height, x : x + width])
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)
            return
        screen_height, screen_width = image.shape[:2]
        self._set_template_reference(
            filename,
            threshold,
            (int(screen_width), int(screen_height)),
        )

    def _set_template_reference(
        self,
        filename: str,
        threshold: float,
        screen_resolution: tuple[int, int] | None = None,
    ) -> None:
        if self.template_tree is None:
            return
        for item_id in self.template_tree.get_children():
            values = self.template_tree.item(item_id, "values")
            if values and values[0] == filename:
                self.template_tree.item(item_id, values=(filename, threshold))
                if screen_resolution is not None:
                    self.template_resolutions[item_id] = screen_resolution
                self.template_tree.selection_set(item_id)
                return
        item_id = self.template_tree.insert(
            "", "end", values=(filename, threshold)
        )
        self.template_resolutions[item_id] = screen_resolution
        self.template_tree.selection_set(item_id)

    def _edit_threshold(self) -> None:
        if self.template_tree is None:
            return
        selection = self.template_tree.selection()
        if not selection:
            return
        item = selection[0]
        values = self.template_tree.item(item, "values")
        threshold = simpledialog.askfloat(
            "识别阈值",
            "请输入 0 到 1 之间的阈值：",
            initialvalue=float(values[1]),
            minvalue=0.0,
            maxvalue=1.0,
            parent=self,
        )
        if threshold is not None:
            self.template_tree.item(item, values=(values[0], threshold))

    def _remove_template(self) -> None:
        if self.template_tree is not None:
            for item in self.template_tree.selection():
                self.template_resolutions.pop(item, None)
                self.branch_steps.pop(item, None)
                self.template_tree.delete(item)

    def _edit_branch(self) -> None:
        if self.template_tree is None:
            return
        selection = self.template_tree.selection()
        if not selection:
            messagebox.showinfo("编辑分支", "请先选择模板，再编辑其分支步骤。", parent=self)
            return
        item = selection[0]
        values = self.template_tree.item(item, "values")
        filename = str(values[0]) if values else "模板"
        dialog = BranchStepDialog(
            self,
            filename,
            self.adb,
            self.template_dir,
            self.presets,
            self.branch_steps.get(item, []),
        )
        self.wait_window(dialog)
        if dialog.result is not None:
            self.branch_steps[item] = dialog.result

    def _pick_tap_position(self) -> None:
        self._pick_point("x", "y")

    def _pick_retry_tap_position(self) -> None:
        self._pick_point("tap_between_x", "tap_between_y")

    def _pick_recognition_target_position(self) -> None:
        self._pick_point("click_x", "click_y")

    def _pick_point(self, x_key: str, y_key: str) -> None:
        try:
            image = self.adb.screenshot()
            max_width, max_height = image_window_bounds(self)
            self.withdraw()
            point = select_point(
                "移动查看坐标，单击选取位置，Esc 取消",
                image,
                max_width,
                max_height,
            )
        except DeviceError as exc:
            messagebox.showerror("截图失败", str(exc), parent=self)
            return
        finally:
            self.deiconify()
        if point is None:
            return
        x, y = point
        x_var = self.field_vars.get(x_key)
        y_var = self.field_vars.get(y_key)
        if x_var is not None and y_var is not None:
            x_var.set(x)
            y_var.set(y)

    def _pick_swipe_range(self) -> None:
        self._pick_swipe(("x1", "y1", "x2", "y2"))

    def _pick_retry_swipe_range(self) -> None:
        self._pick_swipe(("x1", "y1", "x2", "y2"))

    def _pick_swipe(self, keys: tuple[str, str, str, str]) -> None:
        try:
            image = self.adb.screenshot()
            max_width, max_height = image_window_bounds(self)
            self.withdraw()
            swipe = select_swipe(
                "按住鼠标拖动选择滑动范围和方向，Esc 取消",
                image,
                max_width,
                max_height,
            )
        except DeviceError as exc:
            messagebox.showerror("截图失败", str(exc), parent=self)
            return
        finally:
            self.deiconify()
        if swipe is None:
            return
        for key, value in zip(keys, swipe):
            variable = self.field_vars.get(key)
            if variable is not None:
                variable.set(value)

    def _save(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("无法保存", "步骤名称不能为空。", parent=self)
            return
        definition = self.definitions_by_label[self.type_var.get()]
        try:
            params = self._read_params(definition)
        except ValueError as exc:
            messagebox.showerror("参数无效", str(exc), parent=self)
            return
        try:
            screen_resolution = self.adb.screen_resolution()
        except DeviceError as exc:
            messagebox.showerror(
                "无法保存",
                f"无法获取当前手机屏幕分辨率：{exc}",
                parent=self,
            )
            return
        if (
            self.source is not None
            and self.source.kind == definition.key
            and self.source.screen_resolution is not None
            and self.source.screen_resolution != screen_resolution
        ):
            source_width, source_height = self.source.screen_resolution
            target_width, target_height = screen_resolution
            for field in definition.fields:
                if field.coordinate_axis is None:
                    continue
                try:
                    original = int(self.source.params.get(field.key, field.default))
                    current = int(params[field.key])
                except (KeyError, TypeError, ValueError):
                    continue
                if current != original:
                    continue
                scale = (
                    target_width / source_width
                    if field.coordinate_axis == "x"
                    else target_height / source_height
                )
                scaled = int(round(current * scale))
                if not field.coordinate_offset:
                    maximum = (
                        target_width - 1
                        if field.coordinate_axis == "x"
                        else target_height - 1
                    )
                    scaled = max(0, min(maximum, scaled))
                params[field.key] = scaled
        for item in params.get("templates", []):
            if isinstance(item, dict) and "screen_resolution" not in item:
                width, height = screen_resolution
                item["screen_resolution"] = {"width": width, "height": height}
        failure = next(
            (key for key, label in FAILURE_LABELS.items() if label == self.failure_var.get()),
            "stop",
        )
        depends_on: list[str] = []
        if self.dep_list is not None:
            depends_on = [
                self.earlier_steps[index].id
                for index in self.dep_list.curselection()
                if 0 <= index < len(self.earlier_steps)
            ]
        self.result = Step(
            id=self.source.id if self.source else Step(name="", kind="").id,
            name=name,
            kind=definition.key,
            enabled=self.enabled_var.get(),
            on_failure=failure if definition.can_fail else "stop",
            depends_on=depends_on,
            params=params,
            screen_resolution=screen_resolution,
        )
        self.destroy()

    def _read_params(self, definition: StepDefinition) -> dict[str, Any]:
        params: dict[str, Any] = {}
        for spec in definition.fields:
            if spec.kind == "templates":
                if self.template_tree is None:
                    params[spec.key] = []
                    continue
                items = []
                for item_id in self.template_tree.get_children():
                    filename, threshold = self.template_tree.item(item_id, "values")
                    item = {"file": str(filename), "threshold": float(threshold)}
                    resolution = self.template_resolutions.get(item_id)
                    if resolution is not None:
                        width, height = resolution
                        item["screen_resolution"] = {
                            "width": width,
                            "height": height,
                        }
                    items.append(item)
                if not items:
                    raise ValueError("识别步骤至少需要一个模板。")
                params[spec.key] = items
                branches: dict[str, list[dict[str, Any]]] = {}
                for index, item_id in enumerate(self.template_tree.get_children()):
                    branch = self.branch_steps.get(item_id) or []
                    if branch:
                        branches[str(index)] = [
                            branch_step.to_dict() for branch_step in branch
                        ]
                if branches:
                    params["branches"] = branches
                continue

            variable = self.field_vars[spec.key]
            if spec.key == "require_all":
                params[spec.key] = str(variable.get()).strip() == "全部模板匹配"
            elif spec.kind == "bool":
                params[spec.key] = bool(variable.get())
            elif spec.kind == "int":
                params[spec.key] = int(str(variable.get()).strip())
            elif spec.kind == "float":
                params[spec.key] = float(str(variable.get()).strip())
            elif spec.kind == "preset":
                selected_name = str(variable.get()).strip()
                preset_id = next(
                    (
                        preset.id
                        for preset in self.presets
                        if preset.name == selected_name
                    ),
                    "",
                )
                params[spec.key] = preset_id
                params["preset_name"] = selected_name
            elif spec.kind == "choice":
                selected_label = str(variable.get()).strip()
                params[spec.key] = next(
                    (value for value, label in spec.options if label == selected_label),
                    selected_label,
                )
            else:
                params[spec.key] = str(variable.get()).strip()

        if definition.key == "find_and_tap":
            if params["attempts"] < 0:
                raise ValueError("识别次数必须大于或等于 0（0 表示无限重试）。")
            if params["interval"] < 0 or params["wait_after"] < 0:
                raise ValueError("等待时间不能小于 0。")
            if params.get("tap_mode") == "multi":
                if params["click_count"] < 1:
                    raise ValueError("连击次数必须大于 0。")
                if params["click_interval"] < 0:
                    raise ValueError("连击间隔不能小于 0。")
        elif definition.key == "wait" and params["seconds"] < 0:
            raise ValueError("等待时间不能小于 0。")
        return params


class BranchStepDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        template_label: str,
        adb: AdbClient,
        template_dir: Path,
        presets: list[Preset],
        steps: list[Step],
    ) -> None:
        super().__init__(parent)
        self.title(f"分支步骤 - {template_label}")
        self.transient(parent)
        self.resizable(False, True)
        self.adb = adb
        self.template_dir = template_dir
        self.presets = presets
        self.source_steps = list(steps)
        self.result: list[Step] | None = None

        body = ttk.Frame(self, padding=16)
        body.grid(sticky="nsew")
        columns = ("order", "name", "kind", "summary")
        self.step_tree = ttk.Treeview(
            body,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=10,
        )
        headings = {
            "order": "顺序",
            "name": "步骤名称",
            "kind": "类型",
            "summary": "参数摘要",
        }
        widths = {"order": 55, "name": 180, "kind": 110, "summary": 280}
        for column in columns:
            self.step_tree.heading(column, text=headings[column])
            self.step_tree.column(
                column,
                width=widths[column],
                stretch=column in {"name", "summary"},
                anchor="w" if column in {"name", "summary"} else "center",
            )
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.step_tree.yview)
        self.step_tree.configure(yscrollcommand=scrollbar.set)
        self.step_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.step_tree.bind("<Double-1>", lambda _event: self._edit())

        controls = ttk.Frame(body)
        controls.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        for text, command in (
            ("新增", self._add),
            ("编辑", self._edit),
            ("复制", self._duplicate),
            ("删除", self._delete),
            ("上移", lambda: self._move(-1)),
            ("下移", lambda: self._move(1)),
        ):
            ttk.Button(controls, text=text, command=command).pack(
                side="left", padx=(0, 6)
            )
        ttk.Label(
            controls,
            text="识别到该模板后依次执行；执行完毕重新开始当前预设。",
            foreground="#64748b",
        ).pack(side="right")

        buttons = ttk.Frame(body)
        buttons.grid(row=2, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(buttons, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="保存", command=self._save).pack(
            side="right", padx=(0, 8)
        )

        self._refresh()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.grab_set()
        self.wait_visibility()
        self.focus_set()

    def _refresh(self) -> None:
        self.step_tree.delete(*self.step_tree.get_children())
        for index, step in enumerate(self.source_steps, start=1):
            definition = REGISTRY.get(step.kind)
            kind_label = definition.label if definition else step.kind
            self.step_tree.insert(
                "",
                "end",
                values=(index, step.name, kind_label, step_summary(step)),
            )

    def _selected_index(self) -> int | None:
        selection = self.step_tree.selection()
        if not selection:
            return None
        return self.step_tree.index(selection[0])

    def _open_step(self, step: Step | None, earlier: list[Step]) -> Step | None:
        dialog = StepDialog(self, step, self.adb, self.template_dir, earlier, self.presets)
        self.wait_window(dialog)
        return dialog.result

    def _add(self) -> None:
        index = self._selected_index()
        if index is None:
            earlier = list(self.source_steps)
        else:
            earlier = list(self.source_steps[: index + 1])
        edited = self._open_step(None, earlier)
        if edited is None:
            return
        if index is None:
            self.source_steps.append(edited)
        else:
            self.source_steps.insert(index + 1, edited)
        self._refresh()

    def _edit(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        edited = self._open_step(self.source_steps[index], self.source_steps[:index])
        if edited is None:
            return
        self.source_steps[index] = edited
        self._refresh()

    def _duplicate(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        duplicate = Step.from_dict(self.source_steps[index].to_dict())
        duplicate.id = Step(name="", kind="").id
        duplicate.name = f"{duplicate.name} 副本"
        self.source_steps.insert(index + 1, duplicate)
        self._refresh()

    def _delete(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        del self.source_steps[index]
        self._refresh()

    def _move(self, offset: int) -> None:
        index = self._selected_index()
        if index is None:
            return
        destination = index + offset
        if destination < 0 or destination >= len(self.source_steps):
            return
        self.source_steps[index], self.source_steps[destination] = (
            self.source_steps[destination],
            self.source_steps[index],
        )
        self._refresh()

    def _save(self) -> None:
        steps = [Step.from_dict(step.to_dict()) for step in self.source_steps]
        normalize_dependencies(Preset(name="", steps=steps))
        self.result = steps
        self.destroy()


class AutomationConsole:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.store = ConfigStore()
        self.adb = AdbClient(PROJECT_ROOT)
        self.engine = StepEngine(REGISTRY)
        self.stop_event = Event()
        self.events: Queue[tuple[str, Any]] = Queue()
        self.worker: Thread | None = None
        self.dragged_step_id: str | None = None

        self.root.title("ADB 图像自动化控制台")
        self.root.geometry("1120x740")
        self.root.minsize(900, 600)
        self._configure_style()
        try:
            self.config = self.store.load()
        except ConfigError as exc:
            messagebox.showerror("配置错误", str(exc), parent=self.root)
            raise

        self.status_var = tk.StringVar(value="就绪")
        self.device_var = tk.StringVar(value="设备未检查")
        self.preset_var = tk.StringVar()
        self.loop_var = tk.StringVar(value="1")
        applied = set_acceleration(self.config.acceleration)
        if applied != self.config.acceleration:
            self.config.acceleration = applied
        self.accel_var = tk.StringVar(
            value=ACCELERATION_LABELS.get(
                applied, ACCELERATION_LABELS[ACCELERATION_CPU]
            )
        )
        self._build_ui()
        self._refresh_presets()
        self._refresh_steps()
        self._refresh_templates()
        self.root.after(100, self._drain_events)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 15, "bold"))
        style.configure("Status.TLabel", foreground="#475569")
        style.configure("Primary.TButton", font=("Microsoft YaHei UI", 10, "bold"))

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="ADB 图像自动化控制台", style="Title.TLabel").pack(
            side="left"
        )
        ttk.Label(header, textvariable=self.device_var, style="Status.TLabel").pack(
            side="right", padx=(8, 0)
        )
        ttk.Button(header, text="检查设备", command=self._check_device).pack(
            side="right"
        )

        toolbar = ttk.Frame(outer)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Label(toolbar, text="当前预设").pack(side="left")
        self.preset_box = ttk.Combobox(
            toolbar, textvariable=self.preset_var, state="readonly", width=26
        )
        self.preset_box.pack(side="left", padx=(8, 12))
        self.preset_box.bind("<<ComboboxSelected>>", self._select_preset)
        ttk.Button(toolbar, text="新建", command=self._new_preset).pack(side="left")
        ttk.Button(toolbar, text="复制", command=self._duplicate_preset).pack(
            side="left", padx=(5, 0)
        )
        ttk.Button(toolbar, text="重命名", command=self._rename_preset).pack(
            side="left", padx=(5, 0)
        )
        ttk.Button(toolbar, text="删除", command=self._delete_preset).pack(
            side="left", padx=(5, 0)
        )
        preset_file_menu = tk.Menu(toolbar, tearoff=False)
        preset_file_menu.add_command(label="导入预设", command=self._import_preset)
        preset_file_menu.add_command(label="导出当前预设", command=self._export_preset)
        ttk.Menubutton(
            toolbar,
            text="导入 / 导出",
            menu=preset_file_menu,
        ).pack(side="left", padx=(5, 0))

        execution_toolbar = ttk.Frame(outer)
        execution_toolbar.pack(fill="x", pady=(0, 10))
        ttk.Label(execution_toolbar, text="循环次数（0 无限）").pack(
            side="left", padx=(0, 5)
        )
        self.loop_spin = ttk.Spinbox(
            execution_toolbar,
            from_=0,
            to=999999,
            width=7,
            textvariable=self.loop_var,
            command=self._save_loop_count,
        )
        self.loop_spin.pack(side="left")
        self.loop_spin.bind("<Return>", self._save_loop_count)
        self.loop_spin.bind("<FocusOut>", self._save_loop_count)

        ttk.Label(execution_toolbar, text="加速模式").pack(
            side="left", padx=(12, 5)
        )
        self.accel_box = ttk.Combobox(
            execution_toolbar,
            textvariable=self.accel_var,
            values=list(ACCELERATION_LABELS.values()),
            state="readonly",
            width=10,
        )
        self.accel_box.pack(side="left")
        self.accel_box.bind("<<ComboboxSelected>>", self._change_acceleration)

        self.stop_button = ttk.Button(
            execution_toolbar, text="停止", command=self._stop, state="disabled"
        )
        self.stop_button.pack(side="right")
        self.run_button = ttk.Button(
            execution_toolbar,
            text="运行预设",
            command=self._run,
            style="Primary.TButton",
        )
        self.run_button.pack(side="right", padx=(0, 7))

        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)
        sequence_tab = ttk.Frame(notebook, padding=10)
        resource_tab = ttk.Frame(notebook, padding=10)
        log_tab = ttk.Frame(notebook, padding=10)
        notebook.add(sequence_tab, text="步骤编排")
        notebook.add(resource_tab, text="模板资源")
        notebook.add(log_tab, text="运行日志")

        self._build_sequence_tab(sequence_tab)
        self._build_resource_tab(resource_tab)
        self._build_log_tab(log_tab)

        status = ttk.Frame(outer)
        status.pack(fill="x", pady=(9, 0))
        ttk.Label(status, textvariable=self.status_var, style="Status.TLabel").pack(
            side="left"
        )

    def _build_sequence_tab(self, parent: ttk.Frame) -> None:
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        columns = ("order", "enabled", "name", "deps", "kind", "failure", "summary")
        self.step_tree = ttk.Treeview(
            parent, columns=columns, show="headings", selectmode="browse"
        )
        headings = {
            "order": "顺序",
            "enabled": "状态",
            "name": "步骤名称",
            "deps": "关联前置",
            "kind": "类型",
            "failure": "失败处理",
            "summary": "参数摘要",
        }
        widths = {
            "order": 55,
            "enabled": 65,
            "name": 200,
            "deps": 150,
            "kind": 120,
            "failure": 100,
            "summary": 280,
        }
        for column in columns:
            self.step_tree.heading(column, text=headings[column])
            self.step_tree.column(
                column,
                width=widths[column],
                stretch=column in {"name", "deps", "summary"},
                anchor="w" if column in {"name", "deps", "summary"} else "center",
            )
        scrollbar = ttk.Scrollbar(
            parent, orient="vertical", command=self.step_tree.yview
        )
        self.step_tree.configure(yscrollcommand=scrollbar.set)
        self.step_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.step_tree.bind("<Double-1>", lambda _event: self._edit_step())
        self.step_tree.bind("<ButtonPress-1>", self._start_step_drag, add="+")
        self.step_tree.bind("<B1-Motion>", self._drag_step, add="+")
        self.step_tree.bind("<ButtonRelease-1>", self._finish_step_drag, add="+")

        controls = ttk.Frame(parent)
        controls.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(controls, text="新增步骤", command=self._add_step).pack(side="left")
        ttk.Button(controls, text="编辑", command=self._edit_step).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(controls, text="复制", command=self._duplicate_step).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(controls, text="启用 / 停用", command=self._toggle_step).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(controls, text="删除", command=self._delete_step).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(controls, text="下移", command=lambda: self._move_step(1)).pack(
            side="right"
        )
        ttk.Button(controls, text="上移", command=lambda: self._move_step(-1)).pack(
            side="right", padx=(0, 6)
        )

    def _build_resource_tab(self, parent: ttk.Frame) -> None:
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        self.template_tree = ttk.Treeview(
            parent,
            columns=("name", "size"),
            show="headings",
            selectmode="browse",
        )
        self.template_tree.heading("name", text="模板文件")
        self.template_tree.heading("size", text="文件大小")
        self.template_tree.column("name", width=380, anchor="w")
        self.template_tree.column("size", width=120, anchor="center", stretch=False)
        self.template_tree.grid(row=0, column=0, sticky="nsew")

        controls = ttk.Frame(parent)
        controls.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(controls, text="从设备截图新建", command=self._capture_template).pack(
            side="left"
        )
        ttk.Button(controls, text="导入图片", command=self._import_template).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(controls, text="重新截取", command=self._recapture_template).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(controls, text="删除模板", command=self._delete_template).pack(
            side="left", padx=(6, 0)
        )

    def _build_log_tab(self, parent: ttk.Frame) -> None:
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        self.log_text = tk.Text(
            parent,
            wrap="word",
            state="disabled",
            font=("Consolas", 10),
            background="#111827",
            foreground="#e5e7eb",
            insertbackground="#e5e7eb",
            padx=10,
            pady=10,
        )
        scrollbar = ttk.Scrollbar(parent, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        ttk.Button(parent, text="清空日志", command=self._clear_log).grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )

    def _selected_preset(self) -> Preset:
        return self.config.selected_preset()

    def _refresh_presets(self) -> None:
        names = [preset.name for preset in self.config.presets]
        self.preset_box.configure(values=names)
        preset = self._selected_preset()
        self.preset_var.set(preset.name)
        self.loop_var.set(str(preset.loop_count))

    def _refresh_steps(self, select_id: str | None = None) -> None:
        preset = self._selected_preset()
        self.step_tree.delete(*self.step_tree.get_children())
        id_to_name = {step.id: step.name for step in preset.steps}
        for index, step in enumerate(preset.steps, start=1):
            definition = REGISTRY.get(step.kind)
            kind_label = definition.label if definition else step.kind
            can_fail = bool(definition and definition.can_fail)
            dependency_names = "、".join(
                id_to_name.get(dep, dep) for dep in step.depends_on
            )
            self.step_tree.insert(
                "",
                "end",
                iid=step.id,
                values=(
                    index,
                    "启用" if step.enabled else "停用",
                    step.name,
                    dependency_names or "—",
                    kind_label,
                    FAILURE_LABELS.get(step.on_failure, "停止预设") if can_fail else "-",
                    step_summary(step),
                ),
            )
        if select_id and self.step_tree.exists(select_id):
            self.step_tree.selection_set(select_id)
            self.step_tree.focus(select_id)
            self.step_tree.see(select_id)

    def _refresh_templates(self) -> None:
        self.template_tree.delete(*self.template_tree.get_children())
        TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
        for path in sorted(TEMPLATE_DIR.iterdir(), key=lambda item: item.name.lower()):
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}:
                self.template_tree.insert(
                    "", "end", iid=path.name, values=(path.name, f"{path.stat().st_size / 1024:.1f} KB")
                )

    def _save_config(self) -> bool:
        try:
            self.store.save(self.config)
            return True
        except ConfigError as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.root)
            try:
                self.config = self.store.load()
                self._refresh_presets()
                self._refresh_steps()
            except ConfigError:
                pass
            return False

    def _select_preset(self, _event: tk.Event | None = None) -> None:
        selected_name = self.preset_var.get()
        for preset in self.config.presets:
            if preset.name == selected_name:
                self.config.selected_preset_id = preset.id
                self.loop_var.set(str(preset.loop_count))
                self._save_config()
                self._refresh_steps()
                return

    def _save_loop_count(self, _event: tk.Event | None = None) -> bool:
        preset = self._selected_preset()
        try:
            loop_count = int(self.loop_var.get().strip())
            if loop_count < 0:
                raise ValueError
        except ValueError:
            self.loop_var.set(str(preset.loop_count))
            self.status_var.set("循环次数必须是大于或等于 0 的整数")
            return False
        if preset.loop_count == loop_count:
            return True
        preset.loop_count = loop_count
        return self._save_config()

    def _change_acceleration(self, _event: tk.Event | None = None) -> None:
        selected = self.accel_var.get()
        mode = next(
            (
                key
                for key, label in ACCELERATION_LABELS.items()
                if label == selected
            ),
            ACCELERATION_CPU,
        )
        applied = set_acceleration(mode)
        if applied != mode:
            self.accel_var.set(ACCELERATION_LABELS[applied])
            messagebox.showwarning(
                "加速模式",
                "GPU 加速不可用（未检测到可用的 CUDA 或 OpenCL 设备），"
                "已回退到 CPU 加速。",
                parent=self.root,
            )
        self.config.acceleration = applied
        self._save_config()
        self.status_var.set(self._acceleration_status())
        self._append_log(f"已切换加速模式：{self._acceleration_status()}")

    def _acceleration_status(self) -> str:
        backend = acceleration_backend()
        suffix = f"（{backend}）" if backend else ""
        return f"{ACCELERATION_LABELS.get(get_acceleration(), ACCELERATION_LABELS[ACCELERATION_CPU])}{suffix}"

    def _unique_name(self, name: str, exclude_id: str | None = None) -> bool:
        return not any(
            preset.name == name and preset.id != exclude_id
            for preset in self.config.presets
        )

    def _ask_preset_name(self, title: str, initial: str = "") -> str | None:
        name = simpledialog.askstring(
            title, "预设名称：", initialvalue=initial, parent=self.root
        )
        if name is None:
            return None
        name = name.strip()
        if not name:
            messagebox.showerror("名称无效", "预设名称不能为空。", parent=self.root)
            return None
        return name

    def _new_preset(self) -> None:
        name = self._ask_preset_name("新建预设", "新预设")
        if name is None:
            return
        if not self._unique_name(name):
            messagebox.showerror("名称重复", "已有同名预设。", parent=self.root)
            return
        preset = Preset(name=name)
        self.config.presets.append(preset)
        self.config.selected_preset_id = preset.id
        self._save_config()
        self._refresh_presets()
        self._refresh_steps()

    def _duplicate_preset(self) -> None:
        source = self._selected_preset()
        name = self._ask_preset_name("复制预设", f"{source.name} 副本")
        if name is None:
            return
        if not self._unique_name(name):
            messagebox.showerror("名称重复", "已有同名预设。", parent=self.root)
            return
        preset = Preset.from_dict(source.to_dict())
        preset.id = Preset(name="").id
        preset.name = name
        id_remap = {step.id: Step(name="", kind="").id for step in preset.steps}
        for step in preset.steps:
            step.id = id_remap[step.id]
            step.depends_on = [id_remap.get(dep, dep) for dep in step.depends_on]
        self.config.presets.append(preset)
        self.config.selected_preset_id = preset.id
        self._save_config()
        self._refresh_presets()
        self._refresh_steps()

    def _rename_preset(self) -> None:
        preset = self._selected_preset()
        name = self._ask_preset_name("重命名预设", preset.name)
        if name is None or name == preset.name:
            return
        if not self._unique_name(name, preset.id):
            messagebox.showerror("名称重复", "已有同名预设。", parent=self.root)
            return
        preset.name = name
        self._save_config()
        self._refresh_presets()

    def _delete_preset(self) -> None:
        if len(self.config.presets) <= 1:
            messagebox.showinfo("无法删除", "至少保留一个预设。", parent=self.root)
            return
        preset = self._selected_preset()
        referencing = sorted(
            {
                owner.name
                for owner in self.config.presets
                if owner.id != preset.id
                for step in owner.steps
                if step.kind == "run_preset"
                and str(step.params.get("preset_id", "")) == preset.id
            }
        )
        message = f"确定删除“{preset.name}”吗？"
        if referencing:
            message += (
                "\n\n注意：以下预设中的“执行预设”步骤引用了它，删除后这些步骤将无法执行：\n"
                + "、".join(referencing)
            )
        if not messagebox.askyesno("删除预设", message, parent=self.root):
            return
        self.config.presets.remove(preset)
        self.config.selected_preset_id = self.config.presets[0].id
        self._save_config()
        self._refresh_presets()
        self._refresh_steps()

    def _next_imported_name(self, name: str) -> str:
        if self._unique_name(name):
            return name
        base = f"{name} 导入"
        candidate = base
        index = 2
        while not self._unique_name(candidate):
            candidate = f"{base} {index}"
            index += 1
        return candidate

    def _import_preset(self) -> None:
        if self._is_running():
            messagebox.showinfo("正在运行", "请先停止当前预设。", parent=self.root)
            return
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="导入预设",
            filetypes=[("ADB 预设包", "*.adb-preset.zip *.zip"), ("所有文件", "*.*")],
        )
        if not selected:
            return
        try:
            resolution = self.adb.screen_resolution()
            preset = import_preset(Path(selected), TEMPLATE_DIR, resolution)
        except DeviceError as exc:
            messagebox.showerror(
                "导入失败",
                f"无法获取当前手机屏幕分辨率：{exc}",
                parent=self.root,
            )
            return
        except PresetArchiveError as exc:
            messagebox.showerror("导入失败", str(exc), parent=self.root)
            return

        preset.name = self._next_imported_name(preset.name)
        self.config.presets.append(preset)
        self.config.selected_preset_id = preset.id
        if not self._save_config():
            return
        self._refresh_presets()
        self._refresh_steps()
        self._refresh_templates()
        width, height = resolution
        self.status_var.set(f"已导入预设：{preset.name}（{width} × {height}）")
        self._append_log(f"已导入预设：{preset.name}，坐标已适配 {width} × {height}")

    def _export_preset(self) -> None:
        if self._is_running():
            messagebox.showinfo("正在运行", "请先停止当前预设。", parent=self.root)
            return
        preset = self._selected_preset()
        safe_name = "".join(
            "_" if character in '<>:"/\\|?*' else character
            for character in preset.name
        ).strip(" .") or "preset"
        selected = filedialog.asksaveasfilename(
            parent=self.root,
            title="导出当前预设",
            initialfile=f"{safe_name}.adb-preset.zip",
            defaultextension=".zip",
            filetypes=[("ADB 预设包", "*.adb-preset.zip"), ("ZIP 文件", "*.zip")],
        )
        if not selected:
            return
        try:
            export_preset(preset, TEMPLATE_DIR, Path(selected))
        except PresetArchiveError as exc:
            messagebox.showerror("导出失败", str(exc), parent=self.root)
            return
        self.status_var.set(f"已导出预设：{preset.name}")
        self._append_log(f"已导出预设：{preset.name} -> {selected}")

    def _selected_step_index(self) -> int | None:
        selection = self.step_tree.selection()
        if not selection:
            return None
        step_id = selection[0]
        for index, step in enumerate(self._selected_preset().steps):
            if step.id == step_id:
                return index
        return None

    def _open_step_dialog(
        self, step: Step | None, earlier_steps: list[Step]
    ) -> Step | None:
        if self._is_running():
            messagebox.showinfo("正在运行", "请先停止当前预设。", parent=self.root)
            return None
        dialog = StepDialog(
            self.root,
            step,
            self.adb,
            TEMPLATE_DIR,
            earlier_steps,
            self.config.presets,
        )
        self.root.wait_window(dialog)
        return dialog.result

    def _add_step(self) -> None:
        preset = self._selected_preset()
        index = self._selected_step_index()
        if index is None:
            earlier_steps = list(preset.steps)
        else:
            earlier_steps = list(preset.steps[: index + 1])
        step = self._open_step_dialog(None, earlier_steps)
        if step is None:
            return
        if index is None:
            preset.steps.append(step)
        else:
            preset.steps.insert(index + 1, step)
        self._save_config()
        self._refresh_steps(step.id)

    def _edit_step(self) -> None:
        index = self._selected_step_index()
        if index is None:
            return
        preset = self._selected_preset()
        earlier_steps = list(preset.steps[:index])
        edited = self._open_step_dialog(preset.steps[index], earlier_steps)
        if edited is None:
            return
        preset.steps[index] = edited
        self._save_config()
        self._refresh_steps(edited.id)

    def _duplicate_step(self) -> None:
        index = self._selected_step_index()
        if index is None:
            return
        preset = self._selected_preset()
        duplicate = Step.from_dict(preset.steps[index].to_dict())
        duplicate.id = Step(name="", kind="").id
        duplicate.name = f"{duplicate.name} 副本"
        preset.steps.insert(index + 1, duplicate)
        self._save_config()
        self._refresh_steps(duplicate.id)

    def _toggle_step(self) -> None:
        index = self._selected_step_index()
        if index is None:
            return
        step = self._selected_preset().steps[index]
        step.enabled = not step.enabled
        self._save_config()
        self._refresh_steps(step.id)

    def _delete_step(self) -> None:
        index = self._selected_step_index()
        if index is None:
            return
        preset = self._selected_preset()
        step = preset.steps[index]
        if not messagebox.askyesno(
            "删除步骤", f"确定删除“{step.name}”吗？", parent=self.root
        ):
            return
        del preset.steps[index]
        normalize_dependencies(preset)
        self._save_config()
        self._refresh_steps()

    def _move_step(self, offset: int) -> None:
        index = self._selected_step_index()
        if index is None:
            return
        preset = self._selected_preset()
        destination = index + offset
        if destination < 0 or destination >= len(preset.steps):
            return
        ordered_ids = [step.id for step in preset.steps]
        ordered_ids[index], ordered_ids[destination] = (
            ordered_ids[destination],
            ordered_ids[index],
        )
        step_id = ordered_ids[destination]
        reorder_steps(preset, ordered_ids)
        self._save_config()
        self._refresh_steps(step_id)

    def _start_step_drag(self, event: tk.Event) -> None:
        if self.step_tree.identify_region(event.x, event.y) != "cell":
            self.dragged_step_id = None
            return
        step_id = self.step_tree.identify_row(event.y)
        self.dragged_step_id = step_id or None
        if step_id:
            self.step_tree.selection_set(step_id)

    def _drag_step(self, event: tk.Event) -> None:
        if not self.dragged_step_id or not self.step_tree.exists(self.dragged_step_id):
            return
        target_id = self.step_tree.identify_row(event.y)
        if not target_id or target_id == self.dragged_step_id:
            return
        self.step_tree.move(
            self.dragged_step_id,
            "",
            self.step_tree.index(target_id),
        )

    def _finish_step_drag(self, _event: tk.Event) -> None:
        step_id = self.dragged_step_id
        self.dragged_step_id = None
        if not step_id:
            return
        preset = self._selected_preset()
        ordered_ids = list(self.step_tree.get_children())
        try:
            changed = reorder_steps(preset, ordered_ids)
        except ValueError:
            self._refresh_steps(step_id)
            return
        if changed:
            self._save_config()
        self._refresh_steps(step_id)

    def _check_device(self) -> None:
        if self._is_running():
            return
        self.device_var.set("正在检查设备...")

        def check() -> None:
            try:
                state = self.adb.state()
                self.events.put(("device", f"设备状态：{state}"))
                self.events.put(("log", f"ADB 设备状态：{state}"))
            except DeviceError as exc:
                self.events.put(("device", "设备不可用"))
                self.events.put(("device_error", f"设备检查失败：{exc}"))

        Thread(target=check, daemon=True).start()

    def _run(self) -> None:
        if self._is_running():
            return
        if not self._save_loop_count():
            return
        preset = Preset.from_dict(deepcopy(self._selected_preset().to_dict()))
        self.stop_event.clear()
        self.run_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.loop_spin.configure(state="disabled")
        self.accel_box.configure(state="disabled")
        self.status_var.set(f"正在运行：{preset.name}")
        self._append_log(f"加速模式：{self._acceleration_status()}")

        def execute() -> None:
            try:
                state = self.adb.state()
                if state != "device":
                    raise DeviceError(f"设备状态异常：{state}")
                context = RuntimeContext(
                    device=self.adb,
                    template_dir=TEMPLATE_DIR,
                    stop_event=self.stop_event,
                    log=lambda message: self.events.put(("log", message)),
                    engine=self.engine,
                    presets={
                        preset.id: preset for preset in self.config.presets
                    },
                )
                report = self.engine.run(preset, context)
                self.events.put(("done", report))
            except Exception as exc:
                self.events.put(("error", f"运行失败：{exc}"))
                self.events.put(("done", None))

        self.worker = Thread(target=execute, daemon=True)
        self.worker.start()

    def _stop(self) -> None:
        self.stop_event.set()
        self.status_var.set("正在停止...")
        self._append_log("已请求停止，等待当前 ADB 命令结束。")

    def _capture_region(self, title: str) -> tuple[Any, tuple[int, int, int, int]] | None:
        try:
            image = self.adb.screenshot()
            max_width, max_height = image_window_bounds(self.root)
            self.root.withdraw()
            region = select_region(title, image, max_width, max_height)
        except DeviceError as exc:
            messagebox.showerror("截图失败", str(exc), parent=self.root)
            return None
        finally:
            self.root.deiconify()
        if region is None:
            return None
        return image, region

    def _capture_template_named(self, filename: str, title: str) -> bool:
        captured = self._capture_region(title)
        if captured is None:
            return False
        image, (x, y, width, height) = captured
        try:
            save_image(TEMPLATE_DIR / filename, image[y : y + height, x : x + width])
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.root)
            return False
        self._refresh_templates()
        self._append_log(f"已保存模板：{filename}")
        return True

    def _capture_template(self) -> None:
        if self._is_running():
            messagebox.showinfo("正在运行", "请先停止当前预设。", parent=self.root)
            return
        filename = simpledialog.askstring(
            "新建模板", "模板文件名：", initialvalue="template.png", parent=self.root
        )
        if filename is None:
            return
        filename = Path(filename.strip()).name
        if not filename:
            return
        if Path(filename).suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp"}:
            filename += ".png"
        path = TEMPLATE_DIR / filename
        if path.exists() and not messagebox.askyesno(
            "覆盖模板", f"{filename} 已存在，是否覆盖？", parent=self.root
        ):
            return
        self._capture_template_named(filename, f"框选 {filename} 后按 Enter")

    def _import_template(self) -> None:
        if self._is_running():
            messagebox.showinfo("正在运行", "请先停止当前预设。", parent=self.root)
            return
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="导入模板图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp"), ("所有文件", "*.*")],
        )
        if not selected:
            return
        source = Path(selected)
        destination = TEMPLATE_DIR / source.name
        if destination.exists() and not messagebox.askyesno(
            "覆盖模板", f"{source.name} 已存在，是否覆盖？", parent=self.root
        ):
            return
        try:
            TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        except OSError as exc:
            messagebox.showerror("导入失败", str(exc), parent=self.root)
            return
        self._refresh_templates()
        self._append_log(f"已导入模板：{source.name}")

    def _selected_template_name(self) -> str | None:
        selection = self.template_tree.selection()
        return selection[0] if selection else None

    def _recapture_template(self) -> None:
        if self._is_running():
            messagebox.showinfo("正在运行", "请先停止当前预设。", parent=self.root)
            return
        filename = self._selected_template_name()
        if filename:
            self._capture_template_named(filename, f"重新框选 {filename} 后按 Enter")

    def _delete_template(self) -> None:
        if self._is_running():
            messagebox.showinfo("正在运行", "请先停止当前预设。", parent=self.root)
            return
        filename = self._selected_template_name()
        if not filename:
            return
        if not messagebox.askyesno(
            "删除模板",
            f"确定删除 {filename} 吗？引用它的步骤将无法识别。",
            parent=self.root,
        ):
            return
        try:
            (TEMPLATE_DIR / filename).unlink()
        except OSError as exc:
            messagebox.showerror("删除失败", str(exc), parent=self.root)
            return
        self._refresh_templates()

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "device":
                    self.device_var.set(str(payload))
                elif kind == "error":
                    self._append_log(str(payload))
                    self.status_var.set("执行失败")
                elif kind == "device_error":
                    self._append_log(str(payload))
                elif kind == "done":
                    self.run_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.loop_spin.configure(state="normal")
                    self.accel_box.configure(state="normal")
                    if payload is not None:
                        self.status_var.set(payload.message)
                    elif self.status_var.get() != "执行失败":
                        self.status_var.set("执行结束")
        except Empty:
            pass
        self.root.after(100, self._drain_events)

    def _is_running(self) -> bool:
        return bool(self.worker and self.worker.is_alive())

    def _close(self) -> None:
        self.stop_event.set()
        self.root.destroy()


def run_app() -> None:
    root = tk.Tk()
    AutomationConsole(root)
    root.mainloop()
