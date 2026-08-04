<script setup>
import { computed } from 'vue'
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
const locked = computed(() => uiStore.readOnly || runStore.running || configStore.saving)

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
    <div class="properties-scroll">
      <StepFormPanel v-if="selectedNodes.length === 1" :node-id="selectedNodes[0]" />
      <section v-else-if="selectedNodes.length > 1" class="selection-panel">
        <GitFork :size="24" /><h3>已选择 {{ selectedNodes.length }} 个步骤</h3>
        <button :disabled="locked" @click="selectedNodes.forEach((id) => configStore.mutateStep(id, (step) => { step.enabled = true }, '批量启用'))">全部启用</button>
        <button :disabled="locked" @click="selectedNodes.forEach((id) => configStore.mutateStep(id, (step) => { step.enabled = false }, '批量停用'))">全部停用</button>
        <button class="danger" :disabled="locked" @click="configStore.deleteSteps(selectedNodes); uiStore.clearSelection()"><Trash2 :size="14" />删除所选</button>
      </section>
      <section v-else-if="selectedEdge" class="selection-panel edge-panel">
        <template v-if="selectedEdge.data?.kind === 'return'">
          <GitFork :size="24" /><h3>返回连接</h3>
          <dl><dt>来源</dt><dd>{{ nodeName(selectedEdge.source) }}</dd><dt>回到</dt><dd>{{ nodeName(selectedEdge.target) }}</dd></dl>
          <button class="danger" :disabled="locked" @click="configStore.removeReturn(selectedEdge.source); uiStore.clearSelection()"><Trash2 :size="14" />删除返回连接</button>
        </template>
        <template v-else>
          <GitFork :size="24" /><h3>前置依赖</h3>
          <dl><dt>来源</dt><dd>{{ nodeName(selectedEdge.source) }}</dd><dt>目标</dt><dd>{{ nodeName(selectedEdge.target) }}</dd></dl>
          <button class="danger" :disabled="locked" @click="configStore.removeDependency(selectedEdge.source, selectedEdge.target); uiStore.clearSelection()"><Trash2 :size="14" />删除依赖</button>
        </template>
      </section>
      <section v-else class="preset-inspector">
        <div class="preset-mark">{{ configStore.selectedPreset?.steps.length || 0 }}</div>
        <h3>{{ configStore.selectedPreset?.name }}</h3>
        <dl><dt>循环</dt><dd>{{ configStore.selectedPreset?.loop_count === 0 ? '无限' : `${configStore.selectedPreset?.loop_count} 次` }}</dd><dt>步骤</dt><dd>{{ configStore.selectedPreset?.steps.length }}</dd><dt>加速</dt><dd>{{ configStore.config?.acceleration?.toUpperCase() }}</dd></dl>
      </section>
    </div>
    </template>
  </aside>
</template>
