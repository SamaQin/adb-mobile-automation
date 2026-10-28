<script setup>
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { Check, CircleSlash2, Copy, GitBranch, Play, Power, Trash2, X } from 'lucide-vue-next'
import { useConfigStore } from '../../stores/configStore.js'
import { useRunStore } from '../../stores/runStore.js'
import { useUiStore } from '../../stores/uiStore.js'
import { useWorkflowRun } from '../../composables/useWorkflowRun.js'
import { appearanceFor } from '../../constants/nodeAppearance.js'
import { formatDuration, recordingDuration } from '../../utils/recordedActions.js'

const props = defineProps({
  id: { type: String, required: true },
  data: { type: Object, required: true },
  selected: Boolean,
})

const configStore = useConfigStore()
const runStore = useRunStore()
const uiStore = useUiStore()
const { startWorkflow } = useWorkflowRun()
const appearance = computed(() => appearanceFor(props.data.step?.kind))
const Icon = computed(() => appearance.value.icon)
const locked = computed(() => uiStore.readOnly || runStore.running || runStore.preparing || configStore.saving)
const templates = computed(() => props.data.step?.params?.templates || [])
const branchOutputs = computed(() => Object.entries(props.data.step?.params?.branches || {})
  .filter(([, steps]) => steps?.length)
  .map(([index]) => ({
    index: String(index),
    label: templates.value[Number(index)]?.file || `分支 ${Number(index) + 1}`,
  })))
const configuredBranchCount = computed(() => Object.values(props.data.step?.params?.branches || {}).filter((steps) => steps?.length).length)
const outputLeft = (slot) => `${((slot + 1) / (branchOutputs.value.length + 2)) * 100}%`
const outputWidth = computed(() => `calc(${100 / (branchOutputs.value.length + 2)}% - 4px)`)

function summary(step) {
  const params = step?.params || {}
  if (step?.kind === 'wait') return `${params.seconds ?? 1} 秒`
  if (step?.kind === 'tap') return `(${params.x ?? 0}, ${params.y ?? 0})`
  if (step?.kind === 'swipe') return `(${params.x1 ?? 0}, ${params.y1 ?? 0}) → (${params.x2 ?? 0}, ${params.y2 ?? 0})`
  if (step?.kind === 'find_and_tap') {
    const action = step.params?.tap_mode === 'multi' ? `连击 ${step.params?.click_count ?? 2} 次` : '点击'
    const target = step.params?.custom_click
      ? `(${step.params?.click_x ?? 540}, ${step.params?.click_y ?? 1000})`
      : '识别位置'
    const offset = (step.params?.offset_x || step.params?.offset_y)
      ? ` 偏移 (${step.params?.offset_x ?? 0}, ${step.params?.offset_y ?? 0})`
      : ''
    return `${action} ${target}${offset} · ${templates.value.length ? templates.value.map((item) => item.file).join(' · ') : '未选择模板'}`
  }
  if (step?.kind === 'run_preset') return configStore.presets.find((item) => item.id === params.preset_id)?.name || params.preset_name || '未选择预设'
  if (step?.kind === 'end_loop') return '进入下一轮'
  if (step?.kind === 'recorded_actions') {
    const actions = params.actions || []
    if (!actions.length) return '尚未录制操作'
    return `${actions.length} 个操作 · ${formatDuration(recordingDuration(actions))}`
  }
  return '无参数'
}

function mutate(action) {
  if (locked.value) return
  action()
}

async function runFromStep() {
  if (locked.value || !props.data.step?.enabled) return
  try {
    await startWorkflow(props.data.step.id)
  } catch (error) {
    uiStore.notify(error.message, 'error')
  }
}
</script>

<template>
  <div
    class="step-node"
    :class="[`state-${data.state || 'idle'}`, { selected, disabled: !data.step.enabled }]"
    :style="{ '--node-accent': appearance.color }"
  >
    <Handle id="order-target" type="target" :position="Position.Top" :connectable="!locked" />
    <div class="node-accent" />
    <div v-if="!locked" class="node-actions nodrag">
      <button title="从此步骤运行" :disabled="!data.step.enabled" @click.stop="runFromStep"><Play :size="13" fill="currentColor" /></button>
      <button title="复制步骤" :disabled="locked" @click.stop="mutate(() => configStore.duplicateStep(id))"><Copy :size="13" /></button>
      <button :title="data.step.enabled ? '停用步骤' : '启用步骤'" :disabled="locked" @click.stop="mutate(() => configStore.mutateStep(id, (step) => { step.enabled = !step.enabled }, '切换步骤'))"><Power :size="13" /></button>
      <button title="删除步骤" class="danger" :disabled="locked" @click.stop="mutate(() => configStore.deleteSteps([id]))"><Trash2 :size="13" /></button>
    </div>
    <header>
      <span class="node-order">{{ data.order }}</span>
      <component :is="Icon" :size="15" />
      <strong :title="data.step.name">{{ data.step.name }}</strong>
      <Check v-if="data.state === 'done'" :size="15" class="state-icon success" />
      <X v-else-if="data.state === 'failed'" :size="15" class="state-icon failure" />
      <CircleSlash2 v-else-if="data.state === 'skipped'" :size="15" class="state-icon muted" />
    </header>
    <div class="node-meta">
      <span>{{ data.def?.label || data.step.kind }}</span>
      <span v-if="data.step.on_failure === 'continue'" class="badge warning">可跳过</span>
      <span v-if="configuredBranchCount" class="badge branch"><GitBranch :size="11" />{{ configuredBranchCount }}</span>
      <span v-if="data.returnTargetName" class="badge return" :title="`执行后回到：${data.returnTargetName}`">↺返回</span>
    </div>
    <p :title="summary(data.step)">{{ summary(data.step) }}</p>
    <div v-if="templates.length" class="template-stripe">
      <span v-for="template in templates.slice(0, 3)" :key="template.file" :title="template.file">{{ template.file }}</span>
    </div>
    <Handle id="order-source" type="source" :position="Position.Bottom" :connectable="!locked" :style="{ left: branchOutputs.length ? outputLeft(0) : '50%' }" />
    <span v-if="branchOutputs.length" class="node-output-label default-output-label" :style="{ left: outputLeft(0), width: outputWidth }">默认</span>
    <template v-for="(output, outputIndex) in branchOutputs" :key="output.index">
      <Handle
        :id="`branch-${output.index}`"
        type="source"
        :position="Position.Bottom"
        :connectable="!locked"
        :style="{ left: outputLeft(outputIndex + 1) }"
        class="branch-handle"
      />
      <span class="node-output-label branch-output-label" :style="{ left: outputLeft(outputIndex + 1), width: outputWidth }" :title="output.label">{{ output.label }}</span>
    </template>
    <Handle
      id="dependency-source"
      type="source"
      :position="Position.Right"
      :connectable="!locked"
      class="dependency-handle"
      :class="{ 'dependency-handle-add': !data.outgoingDependencyCount }"
    />
  </div>
</template>
