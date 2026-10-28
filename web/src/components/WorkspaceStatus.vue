<script setup>
import { computed } from 'vue'
import { AlertCircle, CheckCircle2, CircleHelp, LocateFixed, LoaderCircle, Save } from 'lucide-vue-next'
import { useConfigStore } from '../stores/configStore.js'
import { useDeviceStore } from '../stores/deviceStore.js'
import { useRunStore } from '../stores/runStore.js'
import { useUiStore } from '../stores/uiStore.js'

const emit = defineEmits(['focus-node'])
const config = useConfigStore(), run = useRunStore(), device = useDeviceStore(), ui = useUiStore()
const connection = computed(() => ({ connected: '服务已连接', connecting: '正在连接服务', disconnected: '服务连接中断，正在重连' })[run.wsState] || '等待连接服务')
const currentStep = computed(() => [...(run.frames || [])].reverse().find((frame) => frame.step_id)?.step_id)
const runningId = computed(() => run.running ? currentStep.value || Object.entries(run.nodeStates).find(([, node]) => node?.state === 'running')?.[0] : null)
const failedId = computed(() => run.running ? null : Object.entries(run.nodeStates).find(([, node]) => node?.state === 'failed')?.[0])
const stepName = computed(() => {
  const target = runningId.value || failedId.value
  const find = (steps) => {
    for (const step of steps || []) {
      if (step.id === target) return step.name
      for (const children of Object.values(step.params?.branches || {})) { const name = find(children); if (name) return name }
    }
  }
  for (const preset of config.presets) { const name = find(preset.steps); if (name) return name }
  return ''
})
const label = computed(() => {
  if (run.state === 'stopping') return '正在停止 · 等待当前设备操作结束'
  if (run.preparing && !run.running) return '正在准备运行…'
  if (run.running) return `正在运行 · 第 ${run.rootCycle || run.cycle || 1} 轮 · ${stepName.value || '准备执行'}`
  if (run.status === 'failed') return run.message || '运行失败，请查看失败步骤'
  if (run.status === 'completed') return '本次运行已完成'
  if (run.status === 'stopped') return '已停止运行'
  if (ui.readOnly) return '只读模式 · 可查看流程，关闭只读后即可编辑'
  if (!config.selectedPreset?.steps.length) return '从左侧添加第一个步骤，开始编排流程'
  if (!device.connected) return '连接设备后即可运行；现在可以继续编辑和保存流程'
  return '就绪 · 选择步骤编辑参数，或点击运行执行流程'
})
</script>

<template>
  <section class="workspace-status" aria-label="工作台状态">
    <div class="workflow-feedback" :class="{ failed: !run.running && run.status === 'failed' }" role="status">
      <LoaderCircle v-if="run.running || run.preparing" :size="14" class="spin" />
      <AlertCircle v-else-if="run.status === 'failed'" :size="14" />
      <CheckCircle2 v-else :size="14" />
      <span :title="label">{{ label }}</span>
      <button v-if="runningId || failedId" class="status-locate" @click="emit('focus-node', runningId || failedId)"><LocateFixed :size="13" />{{ run.running ? '定位当前步骤' : '定位失败步骤' }}</button>
    </div>
    <div class="workspace-meta">
      <span class="connection-state" :class="{ offline: run.wsState !== 'connected' }" :title="connection"><i />{{ connection }}</span>
      <span class="save-state" :class="{ dirty: config.dirty }"><Save :size="13" />{{ config.saving ? '正在保存…' : config.dirty ? '有未保存修改' : '修改已保存' }}</span>
      <button class="status-help" @click="ui.helpOpen = true"><CircleHelp :size="14" />使用帮助</button>
    </div>
  </section>
</template>

<style scoped>
.workspace-status { display:flex; gap:16px; align-items:center; height:36px; margin-top:8px; padding:0 5px; color:var(--muted); font-size:12px; }
.workflow-feedback { display:flex; align-items:center; gap:7px; min-width:0; flex:1; }
.workflow-feedback > svg { flex:none; color:var(--cyan); }
.workflow-feedback > span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.workflow-feedback.failed { color:var(--red); }
.workflow-feedback.failed > svg { color:var(--red); }
.workspace-meta { display:flex; align-items:center; gap:14px; flex:none; }
.connection-state, .save-state { display:flex; align-items:center; gap:5px; white-space:nowrap; }
.connection-state i { width:6px; height:6px; background:var(--green); border-radius:50%; }
.connection-state.offline { color:var(--amber); }
.connection-state.offline i { background:var(--amber); }
.save-state.dirty { color:var(--amber); }
.status-help, .status-locate { height:26px; min-height:26px; padding:0 6px; background:transparent; border-color:transparent; font-size:12px; white-space:nowrap; }
@media(max-width:1100px) { .workspace-meta { gap:7px; } .connection-state { font-size:0; gap:0; } }
</style>
