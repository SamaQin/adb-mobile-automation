<script setup>
import { computed, markRaw, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Background } from '@vue-flow/background'
import { MiniMap } from '@vue-flow/minimap'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import {
  AlignVerticalJustifyCenter,
  Braces,
  Columns3,
  Copy,
  Eye,
  LocateFixed,
  Lock,
  Minus,
  Pencil,
  Play,
  Plus,
  Power,
  Unlock,
  RotateCcw,
  Rows3,
  Trash2,
} from 'lucide-vue-next'
import { createDefaultLayout, createFlow } from '../flow/createFlow.js'
import { connectionKind, validateConnection } from '../flow/connections.js'
import { draggedPositions, handleSignature, reconcileById, stepBindings, syncNodeBindings, topologySignature } from '../flow/canvasSync.js'
import { exportCanvas, importCanvas } from '../flow/exportImport.js'
import { createRuntimeIndex } from '../flow/runtimeSync.js'
import { orderByLayout } from '../composables/useAutoLayout.js'
import { appearanceFor, descriptionFor } from '../constants/nodeAppearance.js'
import { visibleNodePosition } from '../flow/nodePlacement.js'
import { downloadBlob } from '../api/client.js'
import { useConfigStore } from '../stores/configStore.js'
import { useLayoutStore } from '../stores/layoutStore.js'
import { useRunStore } from '../stores/runStore.js'
import { useUiStore } from '../stores/uiStore.js'
import { useWorkflowRun } from '../composables/useWorkflowRun.js'
import StartNode from './nodes/StartNode.vue'
import StepNode from './nodes/StepNode.vue'
import BranchNode from './nodes/BranchNode.vue'
import GroupNode from './nodes/GroupNode.vue'

const configStore = useConfigStore()
const layoutStore = useLayoutStore()
const runStore = useRunStore()
const uiStore = useUiStore()
const { startWorkflow } = useWorkflowRun()
const flowElement = ref(null)
const fileInput = ref(null)
const nodes = ref([])
const edges = ref([])
const contextMenu = ref(null)
const nodeTypes = { start: markRaw(StartNode), step: markRaw(StepNode), branch: markRaw(BranchNode), group: markRaw(GroupNode) }
const { fitView, zoomIn, zoomOut, screenToFlowCoordinate, setCenter, getViewport, updateNodeInternals } = useVueFlow()
const locked = computed(() => uiStore.readOnly || runStore.running || runStore.preparing || configStore.saving)
const interactionsEnabled = ref(true)
const legendExpanded = ref(false)
const emptyPreset = computed(() => Boolean(configStore.selectedPreset && !configStore.selectedPreset.steps.length))
const quickSteps = computed(() => ['wait', 'tap', 'find_and_tap'].map((kind) => configStore.definitions.find((definition) => definition.key === kind)).filter(Boolean))
const lockReason = computed(() => runStore.running ? '正在运行，可选步骤查看；停止后可编辑' : runStore.preparing ? '正在准备运行，请稍候' : configStore.saving ? '正在保存，可选步骤查看；稍后可编辑' : '只读模式，可选步骤查看；关闭只读后可编辑')
const addFeedback = ref('')
let feedbackTimer = null
watch(() => uiStore.selectedNodeId, (id) => { if (id) uiStore.propertiesCollapsed = false })
let rebuildVersion = 0
let activePresetId = null
let measuredHandles = new Map()
let runtimeIndex = createRuntimeIndex([], [])
let runtimeRevision = runStore.nodeRevision

function applyLayout() {
  const preset = configStore.selectedPreset
  if (!preset) return
  const layout = layoutStore.get(preset.id)
  const groupNodes = layoutStore.groups(preset.id).map((group) => ({
    id: group.id,
    type: 'group',
    position: { x: group.x, y: group.y },
    data: {
      group,
      memberCount: Object.values(layout.__groupOf || {}).filter((owner) => owner === group.id).length,
    },
    style: { width: `${group.width}px`, height: `${group.height}px`, zIndex: 0 },
    selectable: false,
    draggable: !locked.value,
    zIndex: 0,
  }))
  const steps = nodes.value.filter((node) => node.type !== 'group')
  let defaults
  for (const node of steps) {
    const position = layout[node.id] || (defaults ||= createDefaultLayout(preset))[node.id]
    if (position && (position.x !== node.position.x || position.y !== node.position.y)) {
      node.position = { x: position.x, y: position.y }
    }
  }
  nodes.value = [...reconcileById(nodes.value.filter((node) => node.type === 'group'), groupNodes), ...steps]
}

async function rebuildTopology() {
  const preset = configStore.selectedPreset
  const version = ++rebuildVersion
  if (!preset) {
    nodes.value = []
    edges.value = []
    activePresetId = null
    runtimeIndex = createRuntimeIndex([], [])
    return
  }
  const switchedPreset = activePresetId !== preset.id
  activePresetId = preset.id
  const previousNodes = switchedPreset ? [] : nodes.value
  const previousEdges = switchedPreset ? [] : edges.value
  const previousHandles = switchedPreset ? new Map() : measuredHandles
  const flow = createFlow(preset, configStore.definitions, layoutStore.get(preset.id), runStore.nodeStates)
  const measureIds = flow.nodes.filter((node) => previousHandles.get(node.id) !== handleSignature(node)).map((node) => node.id)
  measuredHandles = new Map(flow.nodes.map((node) => [node.id, handleSignature(node)]))
  nodes.value = reconcileById(previousNodes, flow.nodes.map((node) => ({
    ...node,
    selected: uiStore.selectedNodeIds.includes(node.id),
    draggable: !locked.value,
    zIndex: 2,
  })), { preservePosition: !switchedPreset })
  applyLayout()
  // VueFlow removes edges whose endpoints disappear during node replacement.
  // Let its node store settle before supplying the next edges; keep the current
  // edges throughout so same-preset edits never introduce an empty edge frame.
  await nextTick()
  if (version !== rebuildVersion) return
  edges.value = reconcileById(previousEdges, flow.edges.map((edge) => ({
    ...edge,
    selected: uiStore.selectedEdgeId === edge.id,
  })))
  await nextTick()
  if (version === rebuildVersion && measureIds.length) updateNodeInternals(measureIds)
}

const topology = computed(() => topologySignature(configStore.selectedPreset))
watch(topology, rebuildTopology, { immediate: true })
watch(() => layoutStore.revision, applyLayout)
// Ordinary edits render directly from step; undo/import may replace its reference.
watch([
  () => configStore.selectedPreset,
  () => configStore.selectedPreset?.name,
  () => stepBindings(configStore.selectedPreset).map(({ step }) => [step, step.name]),
  () => configStore.definitions,
], () => syncNodeBindings(nodes.value, configStore.selectedPreset, configStore.definitions))
watch(() => configStore.definitions, async (definitions, previous) => {
  const oldDefinitions = new Map((previous || []).map((definition) => [definition.key, definition]))
  const changedKinds = new Set(definitions.filter((definition) => oldDefinitions.get(definition.key) !== definition).map((definition) => definition.key))
  const ids = nodes.value.filter((node) => changedKinds.has(node.data?.step?.kind)).map((node) => node.id)
  if (!ids.length) return
  await nextTick()
  updateNodeInternals(ids.filter((id) => nodes.value.some((node) => node.id === id)))
})

watch([
  () => uiStore.selectedNodeIds,
  () => uiStore.selectedEdgeId,
], () => {
  for (const node of nodes.value) node.selected = uiStore.selectedNodeIds.includes(node.id)
  for (const edge of edges.value) edge.selected = uiStore.selectedEdgeId === edge.id
}, { deep: true })

// VueFlow registers graph objects and emits its own node/edge arrays through
// v-model. Index those replacements too, so primitive edge flags always update
// the registered graph object rather than an obsolete pre-registration copy.
watch([nodes, edges], () => {
  runtimeIndex = createRuntimeIndex(nodes.value, edges.value)
  runtimeIndex.sync(runStore.nodeStates, runStore.running)
  runtimeRevision = runStore.nodeRevision
})

watch([
  () => runStore.nodeRevision,
  // Compatibility for callers replacing nodeStates directly; never deep-watch it.
  () => runStore.nodeStates,
  () => runStore.running,
], ([revision, states, running], [, previousStates, wasRunning]) => {
  const fullSync = states !== previousStates || running !== wasRunning
  const changed = fullSync ? null : runStore.nodeChangesSince(runtimeRevision)
  runtimeIndex.sync(states, running, changed, running !== wasRunning)
  runtimeRevision = revision
})

watch(locked, (value) => {
  for (const node of nodes.value) {
    node.draggable = !value
  }
  if (value) closeContextMenu()
})

function onConnect(connection) {
  if (locked.value) return
  const validation = validateConnection(connection, nodes.value, edges.value)
  if (!validation.valid) {
    if (!validation.duplicate) uiStore.notify(validation.reason, 'error')
    return
  }
  try {
    const kind = connectionKind(connection, nodes.value)
    if (kind === 'order') configStore.connectOrder(connection.source, connection.target)
    else if (kind === 'branch') configStore.connectBranch(connection.source, connection.sourceHandle.slice('branch-'.length), connection.target)
    else if (kind === 'return') configStore.connectReturn(connection.source, connection.target)
    else configStore.addDependency(connection.source, connection.target)
    if (kind !== 'return') layoutStore.autoLayout(configStore.selectedPreset, false)
  } catch (error) {
    uiStore.notify(error.message, 'error')
  }
}

function isValidConnection(connection) {
  // VueFlow also invokes this callback when registering existing edges. Those
  // already represent persisted semantics; editor locks and duplicate checks
  // apply only to a prospective handle connection (which has no edge id).
  if (connection.id) return true
  return !locked.value && validateConnection(connection, nodes.value, edges.value).valid
}

function onNodeClick({ event, node }) {
  if (node.id === 'start' || node.type === 'group') return
  uiStore.selectNode(node.id, event.ctrlKey || event.metaKey || event.shiftKey)
}

function onSelectionChange({ nodes: selectedNodes = [], edges: selectedEdges = [] }) {
  uiStore.selectedNodeIds = selectedNodes
    .map((node) => node.id)
    .filter((id) => id !== 'start' && !id.startsWith('group:'))
  const editableEdge = selectedEdges.find((edge) => ['dependency', 'return'].includes(edge.data?.kind))
  uiStore.selectedEdgeId = editableEdge?.id || null
}

function onEdgeClick({ edge }) {
  if (['dependency', 'return'].includes(edge.data?.kind)) uiStore.selectEdge(edge.id)
}

function onNodeDragStop(payload) {
  if (locked.value || !configStore.selectedPreset) return
  const { node } = payload
  if (node?.type === 'group') {
    layoutStore.moveGroup(configStore.selectedPreset.id, node.id, node.position)
    return
  }
  const positions = draggedPositions(payload)
  if (positions.length) layoutStore.setPositions(configStore.selectedPreset.id, positions)
}

function menuPosition(event) {
  const width = 264
  const height = 420
  return {
    x: Math.max(8, Math.min(event.clientX, window.innerWidth - width - 8)),
    y: Math.max(8, Math.min(event.clientY, window.innerHeight - height - 8)),
  }
}

function openContextMenu(event, value) {
  event.preventDefault()
  event.stopPropagation()
  contextMenu.value = { ...menuPosition(event), ...value }
}

function closeContextMenu() {
  contextMenu.value = null
}

function onNodeContextMenu({ event, node }) {
  if (node.id !== 'start' && node.type !== 'group') uiStore.selectNode(node.id)
  openContextMenu(event, {
    type: node.id === 'start' ? 'start' : node.type === 'group' ? 'group' : 'step',
    nodeId: node.id,
  })
}

function onPaneContextMenu(payload) {
  const event = payload?.event || payload
  openContextMenu(event, {
    type: 'pane',
    position: placement({ x: event.clientX, y: event.clientY }),
  })
}

function onEdgeContextMenu({ event, edge }) {
  if (edge.data?.kind === 'return') {
    uiStore.selectEdge(edge.id)
    return openContextMenu(event, { type: 'return-edge', edgeId: edge.id })
  }
  if (edge.data?.kind !== 'dependency') return openContextMenu(event, { type: 'order-edge', edgeId: edge.id })
  uiStore.selectEdge(edge.id)
  openContextMenu(event, { type: 'edge', edgeId: edge.id })
}

function contextNode() {
  return nodes.value.find((node) => node.id === contextMenu.value?.nodeId)
}

function contextStep() {
  return configStore.findStep(contextMenu.value?.nodeId).step
}

async function runContextStep() {
  const nodeId = contextMenu.value?.nodeId
  closeContextMenu()
  if (!nodeId) return
  try {
    await startWorkflow(nodeId)
  } catch (error) {
    uiStore.notify(error.message, 'error')
  }
}

function openProperties() {
  uiStore.selectNode(contextMenu.value.nodeId)
  uiStore.propertiesCollapsed = false
  closeContextMenu()
}

async function renameContextStep() {
  const nodeId = contextMenu.value.nodeId
  const step = contextStep()
  const presetId = configStore.selectedPreset?.id
  closeContextMenu()
  const name = await uiStore.promptText({ title: '重命名步骤', message: '用容易辨认的名称描述这一步。', initialValue: step?.name || '', confirmLabel: '保存名称' })
  if (locked.value || configStore.selectedPreset?.id !== presetId) return
  if (name?.trim()) configStore.mutateStep(nodeId, (item) => { item.name = name.trim() }, '重命名步骤')
  closeContextMenu()
}

function toggleContextStep() {
  const nodeId = contextMenu.value.nodeId
  configStore.mutateStep(nodeId, (step) => { step.enabled = !step.enabled }, '切换步骤')
  closeContextMenu()
}

function duplicateContextStep() {
  const node = contextNode()
  const copyId = configStore.duplicateStep(contextMenu.value.nodeId)
  if (copyId && node) {
    layoutStore.setPosition(configStore.selectedPreset.id, copyId, { x: node.position.x + 28, y: node.position.y + 28 })
    uiStore.selectNode(copyId)
  }
  closeContextMenu()
}

function deleteContextStep() {
  configStore.deleteSteps([contextMenu.value.nodeId])
  uiStore.notify('已删除步骤，可用 Ctrl / ⌘ + Z 撤销')
  uiStore.clearSelection()
  closeContextMenu()
}

async function renameContextGroup() {
  const node = contextNode()
  const presetId = configStore.selectedPreset?.id
  closeContextMenu()
  const name = await uiStore.promptText({ title: '重命名泳道', initialValue: node?.data?.group?.name || '', confirmLabel: '保存名称' })
  if (locked.value || configStore.selectedPreset?.id !== presetId) return
  if (name?.trim()) layoutStore.renameGroup(presetId, node.id, name)
  closeContextMenu()
}

function deleteContextGroup() {
  layoutStore.removeGroup(configStore.selectedPreset.id, contextMenu.value.nodeId)
  closeContextMenu()
}

function deleteContextEdge() {
  const edge = edges.value.find((item) => item.id === contextMenu.value.edgeId)
  if (edge) configStore.removeDependency(edge.source, edge.target)
  uiStore.clearSelection()
  closeContextMenu()
}

function deleteContextReturnEdge() {
  const edge = edges.value.find((item) => item.id === contextMenu.value.edgeId)
  if (edge) configStore.removeReturn(edge.source)
  uiStore.clearSelection()
  closeContextMenu()
}

function addContextStep(kind) {
  addStep(kind, contextMenu.value.position)
  closeContextMenu()
}

async function createGroup() {
  if (locked.value) return
  const name = await uiStore.promptText({ title: '新建泳道', message: '把相关步骤放在一起，方便查看。', initialValue: '新泳道', confirmLabel: '创建泳道' })
  if (locked.value || !configStore.selectedPreset) return
  if (name == null) return
  layoutStore.createGroup(
    configStore.selectedPreset.id,
    name.trim() || '新泳道',
    uiStore.selectedNodeIds,
    nodes.value,
  )
}

function placement(point = null) {
  return visibleNodePosition({
    rect: flowElement.value.getBoundingClientRect(), zoom: getViewport().zoom,
    screenToFlowCoordinate, nodes: nodes.value, point,
  })
}

function addStep(kind, position = null) {
  if (locked.value || !configStore.selectedPreset) return
  const inspectorWasCollapsed = uiStore.propertiesCollapsed
  const presetId = configStore.selectedPreset.id
  const defaultPosition = position || placement()
  const step = configStore.addStep(kind, uiStore.selectedNodeId)
  layoutStore.setPosition(configStore.selectedPreset.id, step.id, defaultPosition)
  uiStore.selectNode(step.id)
  uiStore.propertiesCollapsed = false
  nextTick(() => {
    if (configStore.selectedPreset?.id !== presetId || !configStore.findStep(step.id).step) return
    const rect = flowElement.value.getBoundingClientRect()
    const zoom = getViewport().zoom
    const visibleZoom = Math.max(0.1, Math.min(zoom, 1, ((rect.width || 640) - 24) / 242, ((rect.height || 480) - 88) / 140))
    if (inspectorWasCollapsed || visibleZoom < zoom) {
      setCenter(defaultPosition.x + 121, defaultPosition.y + 70, { zoom: visibleZoom, duration: 200 })
    }
  })
  const order = configStore.selectedPreset.steps.findIndex((item) => item.id === step.id) + 1
  addFeedback.value = `已添加“${step.name}” · 第 ${order} 步，请在右侧设置`
  window.clearTimeout(feedbackTimer)
  feedbackTimer = window.setTimeout(() => { addFeedback.value = '' }, 4500)
  return step
}

function addQuickStep(event, kind) {
  if (event.detail <= 1) addStep(kind)
}

function onDrop(event) {
  event.preventDefault()
  const kind = event.dataTransfer?.getData('application/x-step-kind')
  if (!kind || locked.value) return
  addStep(kind, placement({ x: event.clientX, y: event.clientY }))
}

function onDragOver(event) {
  event.preventDefault()
  event.dataTransfer.dropEffect = locked.value ? 'none' : 'copy'
}

async function autoLayout() {
  if (locked.value) return
  layoutStore.autoLayout(configStore.selectedPreset)
  await nextTick()
  fitView({ padding: 0.18, duration: 350 })
}

async function resetLayout() {
  if (locked.value) return
  layoutStore.reset(configStore.selectedPreset.id, true)
  await nextTick()
  fitView({ padding: 0.18, duration: 350 })
}

async function reorderByLayout() {
  if (locked.value) return
  const ordered = orderByLayout(configStore.selectedPreset.steps, layoutStore.get(configStore.selectedPreset.id))
  configStore.reorderSteps(ordered.map((step) => step.id))
  layoutStore.autoLayout(configStore.selectedPreset, false)
  await nextTick()
  fitView({ padding: 0.18, duration: 350 })
}

function exportJson() {
  const payload = exportCanvas(configStore.selectedPreset, layoutStore.get(configStore.selectedPreset.id), nodes.value, edges.value)
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  downloadBlob(blob, `${configStore.selectedPreset.name}.canvas.json`)
}

function openImport() {
  if (!locked.value) fileInput.value?.click()
}

async function importJson(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  try {
    const value = JSON.parse(await file.text())
    const result = importCanvas(value)
    configStore.replacePreset(result.preset)
    layoutStore.setLayout(result.preset.id, result.layout)
    await nextTick()
    fitView({ padding: 0.18, duration: 350 })
    uiStore.notify('画布 JSON 已导入', 'success')
  } catch (error) {
    uiStore.notify(error.message, 'error')
  }
}

async function focusNode(stepId) {
  const node = nodes.value.find((item) => item.id === stepId || item.data?.step?.id === stepId)
  if (!node) return
  uiStore.selectNode(node.id)
  await nextTick()
  setCenter(node.position.x + 120, node.position.y + 60, { zoom: Math.max(getViewport().zoom, 0.85), duration: 350 })
}

function keydown(event) {
  if (uiStore.dialog || uiStore.helpOpen || uiStore.screenshotRequest || uiStore.templateDrawerOpen || uiStore.wirelessDeviceOpen || uiStore.recordingOpen) return
  const target = event.target
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(target?.tagName) || target?.isContentEditable) return
  const ctrl = event.ctrlKey || event.metaKey
  if (event.key === 'Escape' && contextMenu.value) {
    closeContextMenu()
  } else if ((event.key === 'Delete' || event.key === 'Backspace') && !locked.value) {
    if (!uiStore.selectedEdgeId && !uiStore.selectedNodeIds.length) return
    event.preventDefault()
    if (uiStore.selectedEdgeId) {
      const selected = edges.value.find((item) => item.id === uiStore.selectedEdgeId)
      if (selected?.data?.kind === 'return') configStore.removeReturn(selected.source)
      else if (selected?.data?.kind === 'dependency') configStore.removeDependency(selected.source, selected.target)
    } else configStore.deleteSteps(uiStore.selectedNodeIds)
    uiStore.notify('已删除，可用 Ctrl / ⌘ + Z 撤销')
    uiStore.clearSelection()
  } else if (ctrl && event.key.toLowerCase() === 'c') {
    event.preventDefault()
    sessionStorage.setItem('adb-flow-copy', JSON.stringify(uiStore.selectedNodeIds))
  } else if (ctrl && event.key.toLowerCase() === 'v' && !locked.value) {
    event.preventDefault()
    const ids = JSON.parse(sessionStorage.getItem('adb-flow-copy') || '[]')
    uiStore.selectedNodeIds = configStore.duplicateSteps(ids)
  }
}

onMounted(() => {
  window.addEventListener('keydown', keydown)
  window.addEventListener('pointerdown', closeContextMenu)
  window.addEventListener('blur', closeContextMenu)
})
onBeforeUnmount(() => {
  window.clearTimeout(feedbackTimer)
  window.removeEventListener('keydown', keydown)
  window.removeEventListener('pointerdown', closeContextMenu)
  window.removeEventListener('blur', closeContextMenu)
})

defineExpose({ nodes, edges, autoLayout, resetLayout, reorderByLayout, exportJson, openImport, focusNode, addStep, fit: () => fitView({ padding: 0.18, duration: 300 }) })
</script>

<template>
  <main ref="flowElement" class="flow-canvas" tabindex="0" @drop="onDrop" @dragover="onDragOver" @contextmenu.prevent>
    <VueFlow
      v-model:nodes="nodes"
      v-model:edges="edges"
      :node-types="nodeTypes"
      :min-zoom="0.1"
      :max-zoom="2.5"
      :nodes-draggable="!locked"
      :nodes-connectable="!locked"
      :elements-selectable="interactionsEnabled"
      :delete-key-code="null"
      :multi-selection-key-code="'Shift'"
      :is-valid-connection="isValidConnection"
      :zoom-on-double-click="false"
      fit-view-on-init
      @connect="onConnect"
      @node-click="onNodeClick"
      @edge-click="onEdgeClick"
      @node-context-menu="onNodeContextMenu"
      @edge-context-menu="onEdgeContextMenu"
      @pane-context-menu="onPaneContextMenu"
      @selection-change="onSelectionChange"
      @pane-click="uiStore.clearSelection()"
      @node-drag-stop="onNodeDragStop"
    >
      <Background pattern-color="#475569" :gap="20" :size="1" />
      <MiniMap :pannable="true" :zoomable="true" node-color="#38bdf8" mask-color="rgba(4, 9, 16, 0.72)" />
    </VueFlow>
    <div class="canvas-toolbar panel" aria-label="画布工具">
      <button title="放大" @click="zoomIn()"><Plus :size="15" /></button>
      <button title="缩小" @click="zoomOut()"><Minus :size="15" /></button>
      <button title="适应视图" @click="fitView({ padding: 0.18, duration: 300 })"><LocateFixed :size="15" /></button>
      <button :title="interactionsEnabled ? '锁定画布交互' : '解锁画布交互'" :disabled="locked" @click="interactionsEnabled = !interactionsEnabled"><component :is="interactionsEnabled ? Unlock : Lock" :size="15" /></button>
      <span />
      <button title="自动布局" :disabled="locked" @click="autoLayout"><AlignVerticalJustifyCenter :size="15" /></button>
      <button title="按布局重排执行顺序" :disabled="locked" @click="reorderByLayout"><Rows3 :size="15" /></button>
      <button title="将所选步骤加入新泳道" :disabled="locked" @click="createGroup"><Columns3 :size="15" /></button>
      <button title="重置布局" :disabled="locked" @click="resetLayout"><RotateCcw :size="15" /></button>
      <span />
      <button title="导出画布 JSON" @click="exportJson"><Braces :size="15" /><small>导出</small></button>
      <button title="导入画布 JSON" :disabled="locked" @click="openImport"><Braces :size="15" /><small>导入</small></button>
    </div>
    <section v-if="emptyPreset" class="canvas-welcome panel" aria-label="添加第一个步骤" @pointerdown.stop @dblclick.stop>
      <span class="eyebrow">从这里开始</span>
      <h2>添加第一个步骤</h2>
      <p>先选一种操作，添加后在右侧设置。</p>
      <div class="quick-steps">
        <button v-for="definition in quickSteps" :key="definition.key" :disabled="locked" :title="locked ? lockReason : descriptionFor(definition.key)" :aria-label="`添加${definition.label}`" @click="addQuickStep($event, definition.key)">
          <component :is="appearanceFor(definition.key).icon" :size="15" :style="{ color: appearanceFor(definition.key).color }" /><span>{{ definition.key === 'find_and_tap' ? '识图点击' : definition.label }}</span><Plus :size="12" />
        </button>
      </div>
      <small>也可把左侧步骤拖到画布空白处。拖动画布查看，滚轮缩放。</small>
      <small v-if="locked" class="welcome-lock">{{ lockReason }}</small>
    </section>
    <aside v-else-if="configStore.selectedPreset" class="canvas-guide panel" aria-label="画布说明" @pointerdown.stop>
      <button class="guide-toggle" :aria-expanded="legendExpanded" aria-controls="canvas-guide-details" @click="legendExpanded = !legendExpanded">连线与快捷键 <span>{{ legendExpanded ? '收起' : '展开' }}</span></button>
      <div v-if="legendExpanded" id="canvas-guide-details" class="guide-details">
        <p><i class="legend-line order" /><span><strong>顺序</strong> 按步骤编号依次执行</span></p>
        <p><i class="legend-line dependency" /><span><strong>依赖</strong> 前一步成功才执行这一步</span></p>
        <p><i class="legend-line branch" /><span><strong>分支</strong> 找到对应图片后执行</span></p>
        <p><i class="legend-line return" /><span><strong>返回</strong> 执行后回到指定步骤</span></p>
        <small>移动卡片只调整位置，不改变执行顺序。</small>
        <small>Shift + 点击多选 · Delete 删除<br />Ctrl / ⌘ + C、V 复制粘贴 · Ctrl / ⌘ + Z 撤销</small>
      </div>
    </aside>
    <div v-if="addFeedback" class="canvas-add-feedback" role="status" aria-live="polite">{{ addFeedback }}</div>
    <div v-if="locked" class="canvas-lock">{{ lockReason }}</div>
    <div
      v-if="contextMenu"
      class="canvas-context-menu panel"
      :style="{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px` }"
      role="menu"
      @pointerdown.stop
      @contextmenu.prevent
    >
      <template v-if="contextMenu.type === 'pane'">
        <header><strong>新增节点</strong><small>步骤类型</small></header>
        <div class="context-node-list">
          <button v-for="definition in configStore.definitions" :key="definition.key" :disabled="locked" @click="addContextStep(definition.key)">
            <component :is="appearanceFor(definition.key).icon" :size="15" :style="{ color: appearanceFor(definition.key).color }" />
            <span>{{ definition.label }}</span><small>{{ descriptionFor(definition.key) }}</small>
          </button>
        </div>
      </template>
      <template v-else-if="contextMenu.type === 'step'">
        <header><strong>{{ contextStep()?.name }}</strong><small>{{ contextNode()?.data?.def?.label || contextStep()?.kind }}</small></header>
        <button v-if="!contextNode()?.data?.isBranch" :disabled="locked || !contextStep()?.enabled" @click="runContextStep"><Play :size="15" fill="currentColor" /><span>从此步骤运行</span></button>
        <button @click="openProperties"><Eye :size="15" /><span>{{ locked ? '查看属性' : '修改属性' }}</span></button>
        <button :disabled="locked" @click="renameContextStep"><Pencil :size="15" /><span>重命名</span></button>
        <button :disabled="locked" @click="toggleContextStep"><Power :size="15" /><span>{{ contextStep()?.enabled ? '停用步骤' : '启用步骤' }}</span></button>
        <button :disabled="locked" @click="duplicateContextStep"><Copy :size="15" /><span>复制步骤</span></button>
        <div class="context-separator" />
        <button class="danger" :disabled="locked" @click="deleteContextStep"><Trash2 :size="15" /><span>删除步骤</span></button>
      </template>
      <template v-else-if="contextMenu.type === 'group'">
        <header><strong>{{ contextNode()?.data?.group?.name }}</strong><small>泳道</small></header>
        <button :disabled="locked" @click="renameContextGroup"><Pencil :size="15" /><span>重命名泳道</span></button>
        <button class="danger" :disabled="locked" @click="deleteContextGroup"><Trash2 :size="15" /><span>删除泳道</span></button>
      </template>
      <template v-else-if="contextMenu.type === 'edge'">
        <header><strong>前置依赖</strong><small>连接线</small></header>
        <button class="danger" :disabled="locked" @click="deleteContextEdge"><Trash2 :size="15" /><span>删除依赖</span></button>
      </template>
      <template v-else-if="contextMenu.type === 'return-edge'">
        <header><strong>返回连接</strong><small>执行后回到目标步骤</small></header>
        <button class="danger" :disabled="locked" @click="deleteContextReturnEdge"><Trash2 :size="15" /><span>删除返回连接</span></button>
      </template>
      <template v-else>
        <header><strong>{{ contextMenu.type === 'start' ? '开始节点' : '顺序连接' }}</strong><small>{{ contextMenu.type === 'start' ? '流程入口' : '自动生成' }}</small></header>
        <button @click="closeContextMenu(); fitView({ padding: 0.18, duration: 300 })"><LocateFixed :size="15" /><span>适应视图</span></button>
        <button v-if="contextMenu.type === 'start'" :disabled="locked" @click="closeContextMenu(); autoLayout()"><AlignVerticalJustifyCenter :size="15" /><span>自动布局</span></button>
      </template>
    </div>
    <input ref="fileInput" type="file" accept="application/json,.json" hidden @change="importJson" />
  </main>
</template>

<style scoped>
.canvas-welcome { position: absolute; z-index: 6; top: 70px; left: 50%; width: min(370px, calc(100% - 32px)); max-height: calc(100% - 90px); padding: 18px; transform: translateX(-50%); overflow-y: auto; background: rgba(19, 28, 39, .96); }
.canvas-welcome h2 { margin: 5px 0 8px; font-size: 17px; }
.canvas-welcome p { margin: 0 0 14px; color: var(--muted); font-size: 12px; }
.quick-steps { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 13px; }
.quick-steps button { padding: 7px 9px; font-size: 12px; }
.canvas-welcome small, .guide-details small { display: block; color: var(--muted); font-size: 11px; line-height: 1.7; }
.canvas-welcome .welcome-lock { margin-top: 8px; color: var(--amber); }
.canvas-guide { position: absolute; z-index: 6; bottom: 12px; left: 12px; width: min(280px, calc(100% - 200px)); background: rgba(19, 28, 39, .94); }
.guide-toggle { display: flex; justify-content: space-between; width: 100%; padding: 7px 10px; border: 0; background: transparent; font-size: 11px; }
.guide-toggle span { color: var(--muted); font-size: 10px; }
.guide-details { padding: 0 11px 10px; }
.guide-details p { display: flex; align-items: center; gap: 8px; margin: 8px 0; font-size: 11px; color: var(--muted); }
.guide-details strong { color: var(--text); font-weight: 500; }
.guide-details small { margin-top: 9px; }
.legend-line { flex: none; width: 23px; border-top: 2px solid #718096; }
.legend-line.order { border-top-style: dashed; }
.legend-line.dependency { border-color: #38bdf8; }
.legend-line.branch { border-color: #fbbf24; }
.legend-line.return { border-color: #f472b6; border-top-style: dashed; }
.canvas-add-feedback { position: absolute; z-index: 7; top: 55px; left: 50%; max-width: calc(100% - 28px); padding: 8px 12px; transform: translateX(-50%); border: 1px solid rgba(52,211,153,.4); border-radius: 6px; color: #a7f3d0; background: rgba(11,40,32,.96); font-size: 12px; pointer-events: none; }
.canvas-lock { top: 49px; max-width: calc(100% - 24px); }
.context-node-list button { flex-wrap: wrap; justify-content: flex-start; }
.context-node-list button small { flex-basis: 100%; padding-left: 22px; text-align: left; white-space: normal; }
:deep(.vue-flow__node.selected .step-node) { outline: 2px solid var(--cyan); outline-offset: 3px; }
@media (max-height: 700px) { .canvas-welcome { padding: 13px; } .guide-details { max-height: 210px; overflow-y: auto; } }
</style>
