<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CircleDot, RefreshCw, Square, X } from 'lucide-vue-next'
import { sendDeviceInput } from '../../api/device.js'
import { useDeviceStream } from '../../composables/useDeviceStream.js'
import { useUiStore } from '../../stores/uiStore.js'
import {
  formatDuration,
  gestureToAction,
  mapPointerToDevice,
  recordingDuration,
} from '../../utils/recordedActions.js'

const props = defineProps({
  resolution: { type: Object, required: true },
  serial: { type: String, default: null },
  stepName: { type: String, default: '' },
})
const emit = defineEmits(['complete', 'cancel'])
const ui = useUiStore()
const {
  canvas: streamCanvas,
  loading: streamLoading,
  live: streamLive,
  error: streamError,
  start: startStream,
  stop: stopStream,
  retry: retryStream,
} = useDeviceStream()

const actions = ref([])
const active = ref(null)
const origin = ref(null)
const inputError = ref('')
const resolutionError = ref(false)
const sending = ref(0)
const finishing = ref(false)
let inputQueue = Promise.resolve()

const canRecord = computed(() => streamLive.value && !streamError.value
  && !inputError.value && !finishing.value)
const canFinish = computed(() => actions.value.length > 0 && sending.value === 0
  && !finishing.value && !resolutionError.value)
const duration = computed(() => recordingDuration(actions.value))
const status = computed(() => {
  if (inputError.value) return '输入已暂停'
  if (streamError.value) return '投屏中断'
  if (!streamLive.value) return '正在连接实时画面'
  if (actions.value.length) return '录制中'
  return '等待第一次输入'
})

function pointFromEvent(event) {
  const canvas = streamCanvas.value
  if (!canvas || !props.resolution) return null
  return mapPointerToDevice(
    { clientX: event.clientX, clientY: event.clientY },
    canvas.getBoundingClientRect(),
    canvas.width,
    canvas.height,
    props.resolution,
  )
}

function dispatchInput(action) {
  sending.value += 1
  const payload = action.type === 'tap'
    ? { type: 'tap', x: action.x, y: action.y }
    : {
      type: 'swipe', x1: action.x1, y1: action.y1,
      x2: action.x2, y2: action.y2, duration: action.duration,
    }
  if (props.serial) payload.serial = props.serial
  inputQueue = inputQueue
    .then(() => sendDeviceInput(payload))
    .catch((error) => {
      inputError.value = error?.message || '操作发送失败，请取消后重试'
    })
    .finally(() => { sending.value -= 1 })
}

function onPointerDown(event) {
  if (!canRecord.value || active.value || event.button !== 0 || event.isPrimary === false) return
  const point = pointFromEvent(event)
  if (!point) return
  event.preventDefault()
  if (typeof event.currentTarget.setPointerCapture === 'function') {
    try {
      event.currentTarget.setPointerCapture(event.pointerId)
    } catch {
      // Pointer capture is an enhancement; pointermove/up still arrive on the layer.
    }
  }
  active.value = {
    pointerId: event.pointerId,
    start: point,
    last: point,
    startTime: performance.now(),
  }
}

function onPointerMove(event) {
  if (!active.value || active.value.pointerId !== event.pointerId) return
  const point = pointFromEvent(event)
  if (point) active.value.last = point
}

function onPointerUp(event) {
  if (!active.value || active.value.pointerId !== event.pointerId) return
  const gesture = active.value
  active.value = null
  const point = pointFromEvent(event) || gesture.last
  const now = performance.now()
  if (origin.value === null) origin.value = gesture.startTime
  const action = gestureToAction({
    start: gesture.start,
    end: point,
    duration: Math.max(1, now - gesture.startTime),
    at: gesture.startTime - origin.value,
    resolution: props.resolution,
  })
  actions.value = [...actions.value, action]
  dispatchInput(action)
}

function onPointerCancel() {
  active.value = null
}

async function finish() {
  if (!canFinish.value || resolutionError.value) return
  if (inputError.value) {
    const confirmed = await ui.confirmAction({
      title: '仍然保存录制？',
      message: '有输入没有成功发送到手机。录制的动作仍会保存，运行时可以重试。',
      confirmLabel: '仍然保存',
    })
    if (!confirmed) return
  }
  finishing.value = true
  await inputQueue
  finishing.value = false
  emit('complete', actions.value.map((action) => ({ ...action })))
}

async function cancel() {
  if (actions.value.length) {
    const confirmed = await ui.confirmAction({
      title: '放弃本次录制？',
      message: `已录制的 ${actions.value.length} 个操作会被丢弃。`,
      confirmLabel: '放弃录制',
      danger: true,
    })
    if (!confirmed) return
  }
  emit('cancel')
}

function actionLabel(action) {
  if (action.type === 'tap') return `点击 (${action.x}, ${action.y})`
  return `滑动 (${action.x1}, ${action.y1}) → (${action.x2}, ${action.y2})`
}

function timeLabel(action) {
  return `+${(action.at / 1000).toFixed(1)} 秒`
}

watch(() => [props.resolution?.width, props.resolution?.height], (next, previous) => {
  if (!previous?.length || !next?.length) return
  if (next.some((value, index) => value !== previous[index]) && actions.value.length) {
    resolutionError.value = true
    inputError.value = '设备分辨率已变化，请取消后重新录制'
  }
})

onMounted(() => {
  ui.recordingOpen = true
  startStream()
})
onBeforeUnmount(() => {
  ui.recordingOpen = false
  stopStream()
})
</script>

<template>
  <div class="modal-backdrop recording-backdrop" @mousedown.self="cancel">
    <section class="recording-modal panel" role="dialog" aria-modal="true" aria-label="录制操作">
      <header>
        <div class="recording-title">
          <CircleDot :size="18" />
          <span><strong>录制操作</strong><small>{{ stepName || '当前步骤' }} · 第一次输入开始计时</small></span>
        </div>
        <div class="recording-header-actions">
          <span class="recording-status" :class="{ live: streamLive && !inputError }"><i />{{ status }}</span>
          <button class="icon-button" title="关闭录制窗口" aria-label="关闭录制窗口" @click="cancel"><X :size="17" /></button>
        </div>
      </header>

      <div class="recording-body">
        <div class="recording-stage">
          <canvas ref="streamCanvas" class="recording-canvas" width="1" height="1" aria-label="手机实时画面" />
          <div
            v-if="streamLive && !streamError"
            class="recording-input-layer"
            :class="{ paused: !canRecord }"
            @pointerdown="onPointerDown"
            @pointermove="onPointerMove"
            @pointerup="onPointerUp"
            @pointercancel="onPointerCancel"
          />
          <div v-if="streamLoading && !streamLive" class="recording-state">
            <RefreshCw :size="24" class="spin" /><strong>正在连接实时画面</strong>
          </div>
          <div v-else-if="streamError" class="recording-state error">
            <Square :size="22" /><strong>实时画面中断</strong><span>{{ streamError }}</span>
            <button @click="retryStream"><RefreshCw :size="13" />重试</button>
          </div>
          <div v-else-if="!streamLive" class="recording-state">
            <RefreshCw :size="22" />等待实时画面
          </div>
        </div>

        <aside class="recording-sidebar">
          <div class="recording-summary">
            <span>已录制 <strong>{{ actions.length }}</strong> 个操作</span>
            <span>{{ formatDuration(duration) }}</span>
          </div>
          <p v-if="inputError" class="recording-error" role="alert">{{ inputError }}</p>
          <ol v-if="actions.length" class="recording-actions">
            <li v-for="(action, index) in actions" :key="index" class="recording-action">
              <span class="action-index">{{ index + 1 }}</span>
              <span class="action-copy"><strong>{{ actionLabel(action) }}</strong><small>{{ timeLabel(action) }}</small></span>
            </li>
          </ol>
          <div v-else class="recording-empty">
            <CircleDot :size="22" />
            <strong>等待第一次输入</strong>
            <span>在手机上点击、长按或拖动开始录制；第一次输入前的等待不会保存。</span>
          </div>
          <p class="recording-help">最后一次输入结束后点击“完成录制”。最后输入到点击按钮之间的等待不会保存。</p>
        </aside>
      </div>

      <footer>
        <span class="recording-tip">松手后操作会发送到手机；滑动不跟手是预期行为。</span>
        <button @click="cancel">取消</button>
        <button class="primary" :disabled="!canFinish" @click="finish">完成录制</button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.recording-backdrop { z-index: 300; display: grid; place-items: center; }
.recording-modal { display: grid; width: min(1120px, calc(100vw - 36px)); height: min(760px, calc(100vh - 36px)); grid-template-rows: 58px minmax(0, 1fr) 56px; overflow: hidden; background: #101a27; }
.recording-modal > header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 8px 14px; border-bottom: 1px solid var(--line, #273548); }
.recording-title, .recording-header-actions { display: flex; align-items: center; gap: 9px; }
.recording-title > span { display: flex; flex-direction: column; gap: 2px; }
.recording-title small { color: var(--muted, #94a3b8); font-size: 10px; }
.recording-status { display: flex; align-items: center; gap: 5px; color: var(--muted, #94a3b8); font-size: 11px; white-space: nowrap; }
.recording-status i { width: 6px; height: 6px; border-radius: 50%; background: #64748b; }
.recording-status.live i { background: #f472b6; box-shadow: 0 0 8px #f472b6; }
.recording-body { display: grid; min-height: 0; grid-template-columns: minmax(0, 1fr) 310px; }
.recording-stage { position: relative; min-width: 0; min-height: 0; overflow: hidden; background: #05090e; }
.recording-canvas { display: block; width: 100%; height: 100%; object-fit: contain; background: #05090e; }
.recording-input-layer { position: absolute; inset: 0; touch-action: none; cursor: crosshair; }
.recording-input-layer.paused { cursor: not-allowed; }
.recording-state { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; padding: 24px; color: var(--muted, #94a3b8); text-align: center; background: rgba(5, 9, 14, .78); font-size: 12px; }
.recording-state strong { color: var(--text, #e2e8f0); }
.recording-state.error { color: #fca5a5; }
.recording-sidebar { min-width: 0; overflow-y: auto; padding: 13px; border-left: 1px solid var(--line, #273548); }
.recording-summary { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; color: var(--muted, #94a3b8); font-size: 11px; }
.recording-summary strong { color: var(--text, #e2e8f0); font-size: 16px; }
.recording-error { margin: 10px 0; padding: 8px; border: 1px solid #7f1d1d; border-radius: 6px; color: #fca5a5; background: rgba(127, 29, 29, .22); font-size: 11px; line-height: 1.5; }
.recording-actions { display: grid; gap: 5px; margin: 12px 0 0; padding: 0; list-style: none; }
.recording-action { display: flex; gap: 8px; padding: 7px 8px; border: 1px solid var(--line, #273548); border-radius: 6px; background: rgba(255,255,255,.02); font-size: 11px; }
.action-index { display: grid; flex: none; width: 19px; height: 19px; place-items: center; border-radius: 50%; color: #fbcfe8; background: rgba(244,114,182,.16); font-size: 10px; }
.action-copy { display: flex; min-width: 0; flex-direction: column; gap: 2px; }
.action-copy strong { overflow: hidden; color: var(--text, #e2e8f0); font-weight: 500; text-overflow: ellipsis; white-space: nowrap; }
.action-copy small { color: var(--muted, #94a3b8); }
.recording-empty { display: flex; flex-direction: column; align-items: center; gap: 7px; padding: 42px 8px 24px; color: var(--muted, #94a3b8); text-align: center; }
.recording-empty strong { color: var(--text, #e2e8f0); font-size: 12px; }
.recording-empty span { font-size: 11px; line-height: 1.6; }
.recording-help { margin: 14px 0 0; color: var(--muted, #94a3b8); font-size: 10px; line-height: 1.6; }
.recording-modal > footer { display: flex; align-items: center; justify-content: flex-end; gap: 8px; padding: 8px 14px; border-top: 1px solid var(--line, #273548); }
.recording-tip { margin-right: auto; color: var(--muted, #94a3b8); font-size: 10px; }
@media (max-width: 900px) {
  .recording-body { grid-template-columns: minmax(0, 1fr); }
  .recording-sidebar { display: none; }
}
</style>
