<script setup>
import { computed, ref } from 'vue'
import { MousePointerClick, Trash2 } from 'lucide-vue-next'
import { useConfigStore } from '../../stores/configStore.js'
import { useDeviceStore } from '../../stores/deviceStore.js'
import { useUiStore } from '../../stores/uiStore.js'
import { formatDuration, recordingDuration } from '../../utils/recordedActions.js'
import ActionRecorder from '../recording/ActionRecorder.vue'

const props = defineProps({
  nodeId: { type: String, required: true },
  step: { type: Object, required: true },
  disabled: { type: Boolean, default: false },
})
const configStore = useConfigStore()
const deviceStore = useDeviceStore()
const uiStore = useUiStore()
const recording = ref(false)
const serial = ref(null)
const actions = computed(() => props.step?.params?.actions || [])
const duration = computed(() => recordingDuration(actions.value))

async function ensureReady() {
  let connected = deviceStore.connected
  if (!connected) {
    connected = await deviceStore.check().catch(() => false)
  }
  if (!connected) {
    uiStore.notify('请先连接 ADB 设备，再录制操作。', 'error')
    return false
  }
  if (!deviceStore.resolution) {
    await deviceStore.check().catch(() => false)
  }
  if (!deviceStore.resolution) {
    uiStore.notify('设备尚未返回分辨率，请先检查设备。', 'error')
    return false
  }
  if (!deviceStore.devices.length) {
    await deviceStore.refreshDevices().catch(() => {})
  }
  const chosen = deviceStore.selectedSerial
    || (deviceStore.devices.length === 1 ? deviceStore.devices[0].serial : null)
  if (!chosen && deviceStore.devices.length > 1) {
    uiStore.notify('检测到多台设备，请先在无线设备面板选择录制目标。', 'error')
    return false
  }
  serial.value = chosen || deviceStore.serial || null
  return true
}

async function openRecorder() {
  if (props.disabled) return
  if (!await ensureReady()) return
  recording.value = true
}

async function reRecord() {
  if (!actions.value.length) return openRecorder()
  const confirmed = await uiStore.confirmAction({
    title: '重新录制？',
    message: '已有录制操作会被这次录制替换。',
    confirmLabel: '重新录制',
  })
  if (confirmed) await openRecorder()
}

function complete(next) {
  const resolution = deviceStore.resolution
  if (!resolution) {
    uiStore.notify('设备分辨率不可用，无法保存录制。', 'error')
    recording.value = false
    return
  }
  const value = next.map((action) => ({ ...action }))
  configStore.mutateStep(props.nodeId, (item) => {
    item.params.actions = value
    item.screen_resolution = { width: resolution.width, height: resolution.height }
  }, '录制操作')
  recording.value = false
  uiStore.notify(`已录制 ${value.length} 个操作`, 'success')
}

function cancel() {
  recording.value = false
}

async function clear() {
  if (props.disabled || !actions.value.length) return
  const confirmed = await uiStore.confirmAction({
    title: '清除录制操作？',
    message: '节点会变回“尚未录制”，可用撤销恢复。',
    confirmLabel: '清除',
    danger: true,
  })
  if (!confirmed) return
  configStore.mutateStep(props.nodeId, (item) => {
    item.params.actions = []
    item.screen_resolution = null
  }, '清除录制操作')
}
</script>

<template>
  <div class="recorded-actions-field">
    <div class="recorded-summary">
      <span><MousePointerClick :size="14" /><strong>录制操作</strong></span>
      <span v-if="actions.length">已录制 {{ actions.length }} 个操作 · {{ formatDuration(duration) }}</span>
      <span v-else class="muted">尚未录制</span>
    </div>
    <div class="recorded-buttons">
      <button :disabled="disabled" @click="actions.length ? reRecord() : openRecorder()">
        <MousePointerClick :size="14" />{{ actions.length ? '重新录制' : '录制操作' }}
      </button>
      <button v-if="actions.length" :disabled="disabled" @click="clear"><Trash2 :size="14" />清除</button>
    </div>
    <p class="field-help">
      <template v-if="actions.length">第一次输入开始计时，最后一次输入结束；重录会整段替换。</template>
      <template v-else>打开手机画面，用点击、长按或滑动录制；第一次输入前的等待不会保存。</template>
    </p>
    <ol v-if="actions.length" class="recorded-preview">
      <li v-for="(action, index) in actions.slice(0, 3)" :key="index">
        <span>{{ index + 1 }}</span>
        <strong v-if="action.type === 'tap'">点击 ({{ action.x }}, {{ action.y }})</strong>
        <strong v-else>滑动 ({{ action.x1 }}, {{ action.y1 }}) → ({{ action.x2 }}, {{ action.y2 }})</strong>
        <small>+{{ (action.at / 1000).toFixed(1) }} 秒</small>
      </li>
      <li v-if="actions.length > 3" class="more">还有 {{ actions.length - 3 }} 个操作…</li>
    </ol>
    <Teleport to="body">
      <ActionRecorder
        v-if="recording"
        :resolution="deviceStore.resolution"
        :serial="serial"
        :step-name="step.name"
        @complete="complete"
        @cancel="cancel"
      />
    </Teleport>
  </div>
</template>

<style scoped>
.recorded-actions-field { display: grid; gap: 9px; padding: 3px 0 5px; }
.recorded-summary { display: flex; align-items: center; justify-content: space-between; gap: 10px; color: var(--muted, #94a3b8); font-size: 11px; }
.recorded-summary > span { display: flex; align-items: center; gap: 5px; }
.recorded-summary strong { color: var(--text, #e2e8f0); font-weight: 600; }
.muted { color: var(--muted, #94a3b8); }
.recorded-buttons { display: flex; gap: 7px; }
.recorded-buttons button { display: inline-flex; align-items: center; gap: 5px; }
.recorded-preview { display: grid; gap: 4px; margin: 0; padding: 0; list-style: none; }
.recorded-preview li { display: flex; align-items: baseline; gap: 6px; min-width: 0; padding: 5px 7px; border: 1px solid var(--line, #273548); border-radius: 5px; font-size: 10px; }
.recorded-preview li > span { flex: none; color: #f9a8d4; }
.recorded-preview strong { overflow: hidden; color: var(--text, #e2e8f0); font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.recorded-preview small { margin-left: auto; color: var(--muted, #94a3b8); white-space: nowrap; }
.recorded-preview .more { justify-content: center; color: var(--muted, #94a3b8); }
</style>
