# 录制操作节点 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增“录制操作”步骤：检查器打开带实时手机画面的录制弹窗，录制单指点击/长按/滑动及相对时间，运行时按时间回放。

**Architecture:** 动作列表存入步骤参数；新增 ADB 输入接口提供松手后的反向控制；运行器按 `at` 用可中断等待重放。录制弹窗复用 `useDeviceStream`，坐标层把浏览器坐标映射到原始设备像素。

**Tech Stack:** Python 3.12 / FastAPI / unittest / Vue 3 / Pinia / Vitest / Playwright.

**Spec:** `docs/superpowers/specs/2026-10-28-recorded-actions-node-design.md`

## Global Constraints

- 单指点击、长按、滑动；不支持键盘、多点触控、硬件键。
- 滑动松手后通过 ADB 执行；不做 scrcpy 跟手控制。
- 第一次动作 `at=0`，第一条立即执行；动作间等待保留；最后一条结束即完成。
- 空动作节点运行失败“尚未录制操作”。
- 单节点最多 1000 条动作；单次手势 1–5000ms。
- 动作坐标是原始设备像素；录制时记录 `screen_resolution`。
- 运行期间禁止录制；录制期间禁止运行/编辑快捷键。
- 不新增第三方依赖。
- 工作区已有无关未提交修改；不回滚、不使用 `git add -A`。

## Review Focus

- 首次输入前等待被丢弃，首次动作 `at=0`；最后输入后等待不进入回放。
- 长按/滑动/点击分类和边界（8px、500ms）。
- ADB 输入顺序、运行中 409、显式序列号不回退。
- 空/非法动作、动作时间非递减、坐标/时长上限。
- 分辨率缩放、设备旋转中止、录制字段撤销/重录/清除。

---

### Task 1: 动作模型与回放步骤

**Files:** `model_automation/recorded_actions.py`, `model_automation/registry.py`, `model_automation/steps.py`, `tests/test_steps.py`, `tests/test_operations.py`

- [x] 写失败测试：空动作失败、tap/swipe 顺序与等待、首条立即、无尾部等待、停止、非法动作校验、step_summary。
- [x] 运行确认失败。
- [x] 实现 `normalize_actions`、`FieldSpec("recording")`、`recorded_actions` 定义/runner/summary。
- [x] 运行测试通过。

### Task 2: 预设包坐标缩放

**Files:** `model_automation/preset_archive.py`, `tests/test_preset_archive.py`

- [x] 写失败测试：tap/swipe 坐标缩放、空动作、缺少分辨率、分支递归。
- [x] 实现录制动作缩放。
- [x] 运行测试通过。

### Task 3: 反向输入 API 与序列号

**Files:** `model_automation/device.py`, `web_server/app.py`, `tests/test_device.py`, `tests/test_web_api.py`

- [x] 写失败测试：tap/swipe 路由、非法参数、运行中 409、显式 serial、AdbClient `tap_on/swipe_on`。
- [x] 实现 `_run(serial=...)` 与 `tap_on/swipe_on`，新增 `/api/device/input`。
- [x] 运行测试通过。

### Task 4: 前端纯函数与 API

**Files:** `web/src/api/device.js`, `web/src/utils/recordedActions.js`, tests

- [x] 写失败测试：contain 坐标映射、手势分类、总时长/格式化。
- [x] 实现 `sendDeviceInput` 和纯函数。
- [x] 运行测试通过。

### Task 5: 录制弹窗

**Files:** `web/src/components/recording/ActionRecorder.vue`, `web/src/stores/uiStore.js`, tests

- [x] 写失败测试：空动作不可完成、点击/长按/滑动手势、首条时间 0、输入队列、取消/完成、分辨率变化/输入失败。
- [x] 实现实时画面、指针层、动作列表、完成/取消、输入队列和错误处理。
- [x] 运行测试通过。

### Task 6: 检查器字段与节点摘要

**Files:** `web/src/components/editors/RecordedActionsField.vue`, `StepFormPanel.vue`, `StepNode.vue`, `constants/nodeAppearance.js`, `App.vue`, `FlowCanvas.vue`, tests/build

- [x] 写失败测试：字段空/有动作、打开弹窗、完成写回、重录/清除确认、禁用、节点摘要。
- [x] 实现字段、渲染分支、样式、图标/说明、全局快捷键守卫。
- [x] 运行前端测试、构建。

### Task 7: 完整回归与浏览器冒烟

- [x] 后端完整测试、compileall。
- [x] 前端完整测试、构建。
- [x] 假设备浏览器：打开录制弹窗、模拟点击/滑动、完成、检查摘要；运行节点确认输入调用。
- [x] 检查工作区差异。
