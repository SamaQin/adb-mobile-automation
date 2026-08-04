<script setup>
import { computed, markRaw, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import {
  AlignVerticalJustifyCenter,
  Braces,
  Columns3,
  Copy,
  Eye,
  LocateFixed,
  Pencil,
  Power,
  RotateCcw,
  Rows3,
  Trash2,
} from 'lucide-vue-next'
import { createFlow } from '../flow/createFlow.js'
import { connectionKind, validateConnection } from '../flow/connections.js'
import { exportCanvas, importCanvas } from '../flow/exportImport.js'
import { orderByLayout } from '../composables/useAutoLayout.js'
import { appearanceFor } from '../constants/nodeAppearance.js'
import { downloadBlob } from '../api/client.js'
import { useConfigStore } from '../stores/configStore.js'
import { useLayoutStore } from '../stores/layoutStore.js'
import { useRunStore } from '../stores/runStore.js'
import { useUiStore } from '../stores/uiStore.js'
import StartNode from './nodes/StartNode.vue'
import StepNode from './nodes/StepNode.vue'
import BranchNode from './nodes/BranchNode.vue'
import GroupNode from './nodes/GroupNode.vue'

const configStore = useConfigStore()
const layoutStore = useLayoutStore()
const runStore = useRunStore()
const uiStore = useUiStore()
const flowElement = ref(null)
const fileInput = ref(null)
const nodes = ref([])
const edges = ref([])
const contextMenu = ref(null)
const nodeTypes = { start: markRaw(StartNode), step: markRaw(StepNode), branch: markRaw(BranchNode), group: markRaw(GroupNode) }
const { fitView, screenToFlowCoordinate, setCenter, getViewport, updateNodeInternals } = useVueFlow()
const locked = computed(() => uiStore.readOnly || runStore.running || configStore.saving)
let rebuildVersion = 0

async function rebuild() {
  if (!configStore.selectedPreset) return
  const version = ++rebuildVersion
  const layout = layoutStore.get(configStore.selectedPreset.id)
  const flow = createFlow(
    configStore.selectedPreset,
    configStore.definitions,
    layout,
    runStore.nodeStates,
  )
  const groupNodes = layoutStore.groups(configStore.selectedPreset.id).map((group) => ({
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
  edges.value = []
  await nextTick()
  if (version !== rebuildVersion) return
  nodes.value = [...groupNodes, ...flow.nodes.map((node) => ({
    ...node,
    selected: uiStore.selectedNodeIds.includes(node.id),
    draggable: !locked.value,
    zIndex: 2,
  }))]
  await nextTick()
  if (version !== rebuildVersion) return
  edges.value = flow.edges.map((edge) => ({
    ...edge,
    selected: uiStore.selectedEdgeId === edge.id,
    animated: shouldAnimate(edge),
  }))
  await nextTick()
  if (version !== rebuildVersion) return
  updateNodeInternals(flow.nodes.map((node) => node.id))
}

function shouldAnimate(edge) {
  const sourceId = edge.source.startsWith('branch:') ? edge.source.split(':').at(-1) : edge.source
  const targetId = edge.target.startsWith('branch:') ? edge.target.split(':').at(-1) : edge.target
  const sourceState = runStore.nodeStates[sourceId]?.state || runStore.nodeStates[sourceId]
  const targetState = runStore.nodeStates[targetId]?.state || runStore.nodeStates[targetId]
  return runStore.running && (sourceState === 'running' || targetState === 'running')
}

watch([
  () => configStore.selectedPreset,
  () => configStore.definitions,
  () => layoutStore.revision,
], rebuild, { deep: true, immediate: true })

watch([
  () => uiStore.selectedNodeIds,
  () => uiStore.selectedEdgeId,
], () => {
  for (const node of nodes.value) node.selected = uiStore.selectedNodeIds.includes(node.id)
  for (const edge of edges.value) edge.selected = uiStore.selectedEdgeId === edge.id
}, { deep: true })

watch(() => runStore.nodeStates, () => {
  for (const node of nodes.value) {
    const stepId = node.data?.step?.id
    if (!stepId) continue
    const runtime = runStore.nodeStates[stepId]
    node.data.state = runtime?.state || runtime || 'idle'
    node.data.error = runtime?.error || ''
  }
  for (const edge of edges.value) edge.animated = shouldAnimate(edge)
}, { deep: true })

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
    if (kind !== 'return') layoutStore.autoLayout(configStore.selectedPreset)
  } catch (error) {
    uiStore.notify(error.message, 'error')
  }
}

function isValidConnection(connection) {
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

function onNodeDragStop({ node }) {
  if (node.type === 'group') {
    layoutStore.moveGroup(configStore.selectedPreset.id, node.id, node.position)
    return
  }
  if (node.id === 'start') {
    layoutStore.setPosition(configStore.selectedPreset.id, node.id, node.position)
    return
  }
  layoutStore.assignNodeToGroup(configStore.selectedPreset.id, node.id, node.position)
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
    position: screenToFlowCoordinate({ x: event.clientX, y: event.clientY }),
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

function openProperties() {
  uiStore.selectNode(contextMenu.value.nodeId)
  uiStore.propertiesCollapsed = false
  closeContextMenu()
}

function renameContextStep() {
  const nodeId = contextMenu.value.nodeId
  const step = contextStep()
  const name = window.prompt('步骤名称', step?.name || '')
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
  uiStore.clearSelection()
  closeContextMenu()
}

function renameContextGroup() {
  const node = contextNode()
  const name = window.prompt('泳道名称', node?.data?.group?.name || '')
  if (name?.trim()) layoutStore.renameGroup(configStore.selectedPreset.id, node.id, name)
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
  addStep(kind, contextMenu.value.position, false)
  closeContextMenu()
}

function createGroup() {
  if (locked.value) return
  const name = window.prompt('泳道名称', '新泳道')
  if (name == null) return
  layoutStore.createGroup(
    configStore.selectedPreset.id,
    name.trim() || '新泳道',
    uiStore.selectedNodeIds,
    nodes.value,
  )
}

function addStep(kind, position = null, focus = true) {
  if (locked.value) return
  const step = configStore.addStep(kind, uiStore.selectedNodeId)
  const defaultPosition = position || { x: 80, y: 230 + configStore.selectedPreset.steps.length * 150 }
  layoutStore.setPosition(configStore.selectedPreset.id, step.id, defaultPosition)
  uiStore.selectNode(step.id)
  if (focus) nextTick(() => setCenter(defaultPosition.x + 120, defaultPosition.y + 60, { zoom: getViewport().zoom, duration: 250 }))
}

function onDrop(event) {
  event.preventDefault()
  const kind = event.dataTransfer?.getData('application/x-step-kind')
  if (!kind || locked.value) return
  addStep(kind, screenToFlowCoordinate({ x: event.clientX, y: event.clientY }))
}

function onDragOver(event) {
  event.preventDefault()
  event.dataTransfer.dropEffect = locked.value ? 'none' : 'copy'
}

async function autoLayout() {
  if (locked.value) return
  layoutStore.autoLayout(configStore.selectedPreset)
  rebuild()
  await nextTick()
  fitView({ padding: 0.18, duration: 350 })
}

async function resetLayout() {
  if (locked.value) return
  layoutStore.reset(configStore.selectedPreset.id)
  layoutStore.autoLayout(configStore.selectedPreset)
  rebuild()
  await nextTick()
  fitView({ padding: 0.18, duration: 350 })
}

async function reorderByLayout() {
  if (locked.value) return
  const ordered = orderByLayout(configStore.selectedPreset.steps, layoutStore.get(configStore.selectedPreset.id))
  configStore.reorderSteps(ordered.map((step) => step.id))
  layoutStore.autoLayout(configStore.selectedPreset)
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
  const target = event.target
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(target?.tagName) || target?.isContentEditable) return
  const ctrl = event.ctrlKey || event.metaKey
  if (event.key === 'Escape' && contextMenu.value) {
    closeContextMenu()
  } else if ((event.key === 'Delete' || event.key === 'Backspace') && !locked.value) {
    event.preventDefault()
    if (uiStore.selectedEdgeId) {
      const selected = edges.value.find((item) => item.id === uiStore.selectedEdgeId)
      if (selected?.data?.kind === 'return') configStore.removeReturn(selected.source)
      else if (selected?.data?.kind === 'dependency') configStore.removeDependency(selected.source, selected.target)
    } else configStore.deleteSteps(uiStore.selectedNodeIds)
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
      :elements-selectable="true"
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
      <Controls position="bottom-left" />
    </VueFlow>
    <div class="canvas-toolbar panel" aria-label="画布工具">
      <button title="适应视图" @click="fitView({ padding: 0.18, duration: 300 })"><LocateFixed :size="15" /></button>
      <button title="自动布局" :disabled="locked" @click="autoLayout"><AlignVerticalJustifyCenter :size="15" /></button>
      <button title="按布局重排执行顺序" :disabled="locked" @click="reorderByLayout"><Rows3 :size="15" /></button>
      <button title="将所选步骤加入新泳道" :disabled="locked" @click="createGroup"><Columns3 :size="15" /></button>
      <button title="重置布局" :disabled="locked" @click="resetLayout"><RotateCcw :size="15" /></button>
      <span />
      <button title="导出画布 JSON" @click="exportJson"><Braces :size="15" /><small>导出</small></button>
      <button title="导入画布 JSON" :disabled="locked" @click="openImport"><Braces :size="15" /><small>导入</small></button>
    </div>
    <div v-if="locked" class="canvas-lock">{{ runStore.running ? '运行中' : '只读模式' }}</div>
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
            <span>{{ definition.label }}</span><small>{{ definition.fields.length }} 个参数</small>
          </button>
        </div>
      </template>
      <template v-else-if="contextMenu.type === 'step'">
        <header><strong>{{ contextStep()?.name }}</strong><small>{{ contextNode()?.data?.def?.label || contextStep()?.kind }}</small></header>
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
