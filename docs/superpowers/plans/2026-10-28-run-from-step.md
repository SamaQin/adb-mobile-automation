# 从指定步骤执行到流程末尾 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 允许用户从画布上的任意主流程步骤开始，按原有顺序执行到本次流程末尾。

**Architecture:** 后端在既有运行快照和互斥流程中接收可选起始步骤，写入 `RuntimeContext`；内置 `StepEngine` 从该步骤开始执行后缀，把前缀视为已完成，并把本次运行固定为单轮。前端通过共享组合式函数完成设备检查、脏配置保存、起点校验和启动，节点悬停按钮与右键菜单复用同一入口。

**Tech Stack:** Python 3.12 / FastAPI / unittest / Vue 3 / Pinia / Vue Flow / Vitest。

**Spec:** `docs/superpowers/specs/2026-10-28-run-from-step-design.md`

## Global Constraints

- 只在主流程步骤上提供入口；分支步骤不支持。
- 本次后缀固定只执行一轮；`loop_count=0` 也不能循环。
- 起点之前的步骤不执行，但依赖检查视为已满足。
- 指向起点之前的返回边或 `jump_to` 目标忽略并记录日志。
- 子预设和模板分支仍从各自第一步开始。
- `POST /api/run` 的 `start_step_id` 是可选字段，现有请求语义不变。
- 不改变运行快照、WebSocket、状态、停止和 409/503 错误映射。
- 不新增第三方依赖。
- 工作区已有与本功能无关的未提交修改；不要回滚它们，也不要用 `git add -A` 提交。

## Review Focus

- 从 `loop_count=0` 或 `loop_count>1` 的预设中间起步：只跑一轮后缀，不能卡死或重复。
- 起点依赖一个停用的前缀步骤：起点仍应执行。
- 起点之后的步骤返回起点之前：忽略并记日志，不能执行前缀。
- 起点已停用、不存在或属于分支：开始前拒绝。
- 保存脏配置或设备检查失败：不启动运行，清除“准备中”。

---

### Task 1: 内置引擎支持起始步骤

**Files:**
- Modify: `model_automation/engine.py`
- Test: `tests/test_engine.py`

**Interfaces:**
- Produces: `RuntimeContext.start_step_id: str | None = None`；`StepEngine.run` 读取根 context 的起点并在子 frame 中清空。

- [x] **Step 1: 写失败测试** — `tests/test_engine.py` 的 `StartStepTests` 覆盖后缀、原始 step_index、前缀依赖、停用前缀、有限/无限循环、跨起点返回、后缀内返回、非法起点和子预设不继承起点。
- [x] **Step 2: 运行测试确认失败** — `tests.test_engine.StartStepTests` 因缺少 `start_step_id` 失败。
- [x] **Step 3: 实现引擎起点** — `RuntimeContext` 增加字段；`StepEngine.run` 读取后清空；`_run` 计算起点、assumed 集合、单轮后缀、原始索引和返回边界。
- [x] **Step 4: 运行测试确认通过** — `.venv\Scripts\python.exe -m unittest tests.test_engine` → 32 tests OK。

### Task 2: 运行时与 API 接收起始步骤

**Files:**
- Modify: `web_server/runtime.py`
- Modify: `web_server/app.py`
- Test: `tests/test_web_runtime.py`
- Test: `tests/test_web_api.py`

**Interfaces:**
- Consumes: Task 1 的 `RuntimeContext.start_step_id`。
- Produces: `RuntimeManager.start(preset_id, start_step_id=None)`；`POST /api/run` 接受可选字符串 `start_step_id`。

- [x] **Step 1: 写运行时失败测试** — `StartStepRuntimeTests` 覆盖透传、未知/停用起点拒绝、无起点完整运行。
- [x] **Step 2: 运行测试确认失败** — `RuntimeManager.start` 不接受第二个参数。
- [x] **Step 3: 实现运行时校验与透传** — 在快照内校验主流程/启用状态，把起点写入 `RuntimeContext`。
- [x] **Step 4: 写 API 失败测试** — 带起点只执行后缀；非法起点返回 400。
- [x] **Step 5: 实现 API 参数** — 解析可选 `start_step_id`，空值按未提供处理，非字符串 400。
- [x] **Step 6: 运行测试确认通过** — `tests.test_web_runtime.StartStepRuntimeTests` + API 起点测试 → 4 tests OK；完整后端 232 tests OK。

### Task 3: 前端启动入口与共享准备逻辑

**Files:**
- Modify: `web/src/api/run.js`
- Modify: `web/src/stores/runStore.js`
- Create: `web/src/composables/useWorkflowRun.js`
- Test: `web/src/stores/runStore.test.js`
- Test: `web/src/composables/useWorkflowRun.test.js`

**Interfaces:**
- Produces: `startRun(presetId, startStepId=null)`；`runStore.start(presetId, startStepId=null)`；`runStore.preparing`；`useWorkflowRun().startWorkflow(startStepId=null)`。

- [x] **Step 1: 写 runStore 失败测试** — 无起点保持单参数，有起点转发。
- [x] **Step 2: 运行测试确认失败** — `startRun` 只收到一个参数。
- [x] **Step 3: 实现 API 与 store 参数** — body 按需加入 `start_step_id`；state 增加 `preparing`。
- [x] **Step 4: 写组合式函数失败测试** — 停用起点、脏配置保存、无起点、设备失败、保存失败、无限空预设。
- [x] **Step 5: 实现 `useWorkflowRun`** — 设备检查、脏保存、起点校验、无限空预设校验、清除选择、启动；`finally` 复位。
- [x] **Step 6: 运行测试确认通过** — `npm test -- src/stores/runStore.test.js src/composables/useWorkflowRun.test.js` → 18 tests passed。

### Task 4: 节点按钮、右键菜单与工具栏接入

**Files:**
- Modify: `web/src/components/nodes/StepNode.vue`
- Modify: `web/src/components/FlowCanvas.vue`
- Modify: `web/src/components/editors/PresetToolbar.vue`
- Test: `web/src/components/nodes/StepNode.test.js`
- Test: `web/src/components/FlowCanvas.test.js`
- Test: `web/src/components/editors/PresetToolbar.test.js`

**Interfaces:**
- Consumes: Task 3 的 `useWorkflowRun` 与 `runStore.preparing`。
- Produces: 节点悬停 ▶ 按钮、步骤右键“从此步骤运行”、顶部运行按钮共用同一准备入口。

- [x] **Step 1: 写 StepNode 失败测试** — 按钮存在、点击调用、停用禁用、运行/准备中隐藏、错误提示。
- [x] **Step 2: 运行测试确认失败** — 按钮不存在。
- [x] **Step 3: 实现 StepNode 按钮** — `Play` 图标、`@click.stop`、错误通知、`locked` 增加 preparing。
- [x] **Step 4: 写 FlowCanvas 失败测试** — 主步骤菜单出现入口并调用；分支节点隐藏。
- [x] **Step 5: 实现 FlowCanvas 菜单** — 菜单项、分支隐藏、关闭后调用、错误提示。
- [x] **Step 6: 接入 PresetToolbar** — 复用组合式函数，准备状态改为 `runStore.preparing`，顶部行为不变。
- [x] **Step 7: 运行前端测试** — `npm test` → 178 tests passed。
- [x] **Step 8: 构建前端** — `npm run build` → success。

### Task 5: 完整回归与验收

- [x] **Step 1: 后端完整测试** — 233 tests OK。
- [x] **Step 2: 后端语法检查** — `compileall` exit 0。
- [x] **Step 3: 前端完整测试** — 178 tests passed。
- [x] **Step 4: 前端构建** — success。
- [x] **Step 5: 浏览器冒烟（假设备）** — 从“截图坐标验证”节点启动，日志包含起点，前缀等待节点保持 idle，运行完成，无浏览器错误。
- [x] **Step 6: 检查工作区差异** — 仅功能相关文件 + 原有未提交修改；未提交或回滚原有修改。
