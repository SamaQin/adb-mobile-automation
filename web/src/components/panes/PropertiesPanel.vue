<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { GitFork, Layers3, PanelRightClose, PanelRightOpen, Trash2 } from 'lucide-vue-next'
import { useConfigStore } from '../../stores/configStore.js'
import { useRunStore } from '../../stores/runStore.js'
import { useUiStore } from '../../stores/uiStore.js'
import StepFormPanel from '../editors/StepFormPanel.vue'

const props = defineProps({ edges: { type: Array, default: () => [] } })
const configStore = useConfigStore()
const runStore = useRunStore()
const uiStore = useUiStore()
const selectedEdge = computed(() => props.edges.find((item) => item.id === uiStore.selectedEdgeId))
const selectedNodes = computed(() => uiStore.selectedNodeIds.filter((id) => id !== 'start'))
const locked = computed(() => uiStore.readOnly || runStore.running || runStore.preparing || configStore.saving)
const inspectorScroll = ref(null)
watch(() => [uiStore.selectedNodeIds.join('|'), uiStore.selectedEdgeId], async () => {
  await nextTick()
  if (inspectorScroll.value) inspectorScroll.value.scrollTop = 0
})
const selectedStep = computed(() => selectedNodes.value.length === 1 ? configStore.findStep(selectedNodes.value[0]).step : null)
const execution = computed(() => runStore.nodeStates[selectedStep.value?.id])
const executionState = computed(() => typeof execution.value === 'string' ? execution.value : execution.value?.state || 'idle')
const executionLabel = computed(() => ({ idle: '尚未执行', running: '执行中', done: '执行成功', success: '执行成功', succeeded: '执行成功', completed: '执行成功', failed: '执行失败', skipped: '已跳过', stopped: '已停止' }[executionState.value] || executionState.value))

function nodeName(id) {
  return configStore.findStep(id).step?.name || id
}
</script>

<template>
  <aside class="properties panel" :class="{ collapsed: uiStore.propertiesCollapsed }">
    <button
      v-if="uiStore.propertiesCollapsed"
      class="panel-expand-button"
      title="展开检查器"
      aria-label="展开检查器"
      @click="uiStore.propertiesCollapsed = false"
    ><PanelRightOpen :size="17" /><Layers3 :size="16" /></button>
    <template v-else>
    <div class="panel-heading"><div><span class="eyebrow">检查器</span><h2>属性</h2></div><div class="panel-heading-actions"><Layers3 :size="17" /><button class="panel-collapse-button" title="收起检查器" aria-label="收起检查器" @click="uiStore.propertiesCollapsed = true"><PanelRightClose :size="15" /></button></div></div>
    <div ref="inspectorScroll" class="properties-scroll">
      <template v-if="selectedNodes.length === 1">
        <section class="execution-summary" :class="{ failed: executionState === 'failed' }" aria-label="步骤执行结果" aria-live="polite">
          <div><strong>执行结果</strong><span>{{ executionLabel }}</span></div>
          <p v-if="execution?.error || execution?.message">{{ execution.error || execution.message }}</p>
          <small v-if="execution?.cycle">第 {{ execution.cycle }} 轮</small>
        </section>
        <StepFormPanel :node-id="selectedNodes[0]" />
      </template>
      <section v-else-if="selectedNodes.length > 1" class="selection-panel">
        <GitFork :size="24" /><h3>已选择 {{ selectedNodes.length }} 个步骤</h3>
        <button :disabled="locked" @click="configStore.setStepsEnabled(selectedNodes, true)">全部启用</button>
        <button :disabled="locked" @click="configStore.setStepsEnabled(selectedNodes, false)">全部停用</button>
        <button class="danger" :disabled="locked" @click="configStore.deleteSteps(selectedNodes); uiStore.clearSelection(); uiStore.notify('步骤已删除，可用 Ctrl+Z 撤销')"><Trash2 :size="14" />删除所选</button>
      </section>
      <section v-else-if="selectedEdge" class="selection-panel edge-panel">
        <template v-if="selectedEdge.data?.kind === 'return'">
          <GitFork :size="24" /><h3>返回连接</h3>
          <dl><dt>来源</dt><dd>{{ nodeName(selectedEdge.source) }}</dd><dt>回到</dt><dd>{{ nodeName(selectedEdge.target) }}</dd></dl>
          <button class="danger" :disabled="locked" @click="configStore.removeReturn(selectedEdge.source); uiStore.clearSelection()"><Trash2 :size="14" />删除返回连接</button>
        </template>
        <template v-else>
          <GitFork :size="24" /><h3>前置依赖</h3>
          <p class="inspector-help">来源步骤执行成功，目标步骤才会执行；多个依赖需要全部成功。</p>
          <dl><dt>来源</dt><dd>{{ nodeName(selectedEdge.source) }}</dd><dt>目标</dt><dd>{{ nodeName(selectedEdge.target) }}</dd></dl>
          <button class="danger" :disabled="locked" @click="configStore.removeDependency(selectedEdge.source, selectedEdge.target); uiStore.clearSelection()"><Trash2 :size="14" />删除依赖</button>
        </template>
      </section>
      <section v-else class="preset-inspector">
        <div class="preset-mark">{{ configStore.selectedPreset?.steps.length || 0 }}</div>
        <h3>选择节点编辑</h3>
        <p class="inspector-help">点击画布上的步骤，在这里修改参数。按住 Shift 点击可多选。</p>
        <p class="inspector-help">从左侧添加步骤，按顺序连接后运行；识别成功可进入模板分支，有前置依赖的步骤需等依赖全部成功。</p>
        <strong>{{ configStore.selectedPreset?.name }}</strong>
        <dl><dt>循环</dt><dd>{{ configStore.selectedPreset?.loop_count === 0 ? '无限' : `${configStore.selectedPreset?.loop_count} 次` }}</dd><dt>步骤</dt><dd>{{ configStore.selectedPreset?.steps.length }}</dd><dt>加速</dt><dd>{{ configStore.config?.acceleration?.toUpperCase() }}</dd></dl>
      </section>
    </div>
    </template>
  </aside>
</template>

<style scoped>
.execution-summary { margin-bottom: 16px; padding: 10px 12px; border: 1px solid var(--border, #334155); border-radius: 8px; font-size: 12px; }
.execution-summary > div { display: flex; justify-content: space-between; gap: 12px; }
.execution-summary p { margin: 8px 0 0; line-height: 1.6; overflow-wrap: anywhere; }
.execution-summary small { display: block; margin-top: 7px; color: var(--muted, #94a3b8); }
.execution-summary.failed { border-color: #9f3650; color: #fda4af; }
.inspector-help { font-size: 12px; line-height: 1.7; color: var(--muted, #94a3b8); }
.preset-inspector > strong { display: block; margin-top: 18px; font-size: 13px; }
</style>
