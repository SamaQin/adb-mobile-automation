<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { EyeOff, MonitorCheck, RefreshCw, WifiOff } from 'lucide-vue-next'
import { useDeviceStream } from '../composables/useDeviceStream.js'
import { useDeviceStore } from '../stores/deviceStore.js'
import {
  moveMonitorGeometry,
  normalizeMonitorGeometry,
  readMonitorGeometry,
  resizeMonitorGeometry,
  saveMonitorGeometry,
} from '../utils/floatingWindow.js'

const emit = defineEmits(['hide'])
const deviceStore = useDeviceStore()
const {
  canvas: streamCanvas,
  loading: streamLoading,
  live: streamLive,
  error: streamError,
  start: startStream,
  stop: stopStream,
  retry: retryStream,
} = useDeviceStream()

const geometry = ref(readMonitorGeometry(window.localStorage, viewport()))
const pageVisible = ref(document.visibilityState !== 'hidden')
const dragging = ref(false)
const resizing = ref(false)
let dragState = null
let resizeState = null
let viewportPersistTimer = null

const style = computed(() => ({
  left: `${geometry.value.x}px`,
  top: `${geometry.value.y}px`,
  width: `${geometry.value.width}px`,
  height: `${geometry.value.height}px`,
}))
const streaming = computed(() => deviceStore.connected && pageVisible.value)
const isLive = computed(() => streaming.value && streamLive.value)
const resolutionLabel = computed(() => deviceStore.resolution
  ? `${deviceStore.resolution.width} × ${deviceStore.resolution.height}`
  : '等待设备分辨率')
const statusLabel = computed(() => {
  if (!deviceStore.connected) return '设备未连接'
  if (!pageVisible.value) return '页面后台暂停'
  if (streamError.value) return '实时投屏中断，正在重连'
  if (streamLoading.value && !streamLive.value) return '正在建立低延迟投屏'
  if (streamLive.value) return '低延迟实时投屏'
  return '等待视频流'
})

function viewport() {
  return { width: window.innerWidth, height: window.innerHeight }
}

function persistGeometry() {
  saveMonitorGeometry(window.localStorage, geometry.value)
}

function stopInteraction() {
  dragging.value = false
  resizing.value = false
  dragState = null
  resizeState = null
  document.body.classList.remove('monitor-dragging', 'monitor-resizing')
  window.removeEventListener('pointermove', onInteractionMove)
  window.removeEventListener('pointerup', onInteractionEnd)
  window.removeEventListener('pointercancel', onInteractionEnd)
}

function onInteractionMove(event) {
  if (dragState) {
    geometry.value = moveMonitorGeometry(
      dragState.origin,
      event.clientX - dragState.startX,
      event.clientY - dragState.startY,
      viewport(),
    )
  } else if (resizeState) {
    geometry.value = resizeMonitorGeometry(
      resizeState.origin,
      event.clientX - resizeState.startX,
      event.clientY - resizeState.startY,
      viewport(),
    )
  }
}

function onInteractionEnd() {
  if (!dragState && !resizeState) return
  persistGeometry()
  stopInteraction()
}

function beginDrag(event) {
  if (event.button !== 0 || event.target.closest('button')) return
  event.preventDefault()
  try {
    event.currentTarget.setPointerCapture(event.pointerId)
  } catch {
    // Pointer capture is an enhancement; window listeners still handle the drag.
  }
  dragState = {
    startX: event.clientX,
    startY: event.clientY,
    origin: { ...geometry.value },
  }
  dragging.value = true
  document.body.classList.add('monitor-dragging')
  window.addEventListener('pointermove', onInteractionMove)
  window.addEventListener('pointerup', onInteractionEnd)
  window.addEventListener('pointercancel', onInteractionEnd)
}

function beginResize(event) {
  if (event.button !== 0) return
  event.preventDefault()
  event.stopPropagation()
  try {
    event.currentTarget.setPointerCapture(event.pointerId)
  } catch {
    // Pointer capture is an enhancement; window listeners still handle the resize.
  }
  resizeState = {
    startX: event.clientX,
    startY: event.clientY,
    origin: { ...geometry.value },
  }
  resizing.value = true
  document.body.classList.add('monitor-resizing')
  window.addEventListener('pointermove', onInteractionMove)
  window.addEventListener('pointerup', onInteractionEnd)
  window.addEventListener('pointercancel', onInteractionEnd)
}

function resizeByKeyboard(event) {
  const step = event.shiftKey ? 32 : 12
  const deltas = {
    ArrowRight: [step, 0],
    ArrowLeft: [-step, 0],
    ArrowDown: [0, step],
    ArrowUp: [0, -step],
  }
  if (!deltas[event.key]) return
  event.preventDefault()
  geometry.value = resizeMonitorGeometry(geometry.value, ...deltas[event.key], viewport())
  persistGeometry()
}

function handleViewportResize() {
  geometry.value = normalizeMonitorGeometry(geometry.value, viewport())
  window.clearTimeout(viewportPersistTimer)
  viewportPersistTimer = window.setTimeout(persistGeometry, 180)
}

function handleVisibilityChange() {
  pageVisible.value = document.visibilityState !== 'hidden'
}

function hide() {
  persistGeometry()
  emit('hide')
}

async function checkDevice() {
  try {
    await deviceStore.check()
  } catch {
    // The preview renders the device store error and keeps retrying when connected.
  }
}

watch(streaming, (active) => {
  if (active) startStream()
  else stopStream()
})

onMounted(() => {
  if (streaming.value) startStream()
  window.addEventListener('resize', handleViewportResize)
  window.addEventListener('blur', onInteractionEnd)
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onBeforeUnmount(() => {
  window.clearTimeout(viewportPersistTimer)
  persistGeometry()
  window.removeEventListener('resize', handleViewportResize)
  window.removeEventListener('blur', onInteractionEnd)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  if (dragState || resizeState) stopInteraction()
})
</script>

<template>
  <section
    class="device-monitor panel"
    :class="{ dragging, resizing }"
    :style="style"
    role="region"
    aria-label="手机实时画面"
  >
    <header class="device-monitor-titlebar" title="拖动移动窗口" @pointerdown="beginDrag">
      <MonitorCheck :size="15" />
      <span class="monitor-heading">
        <strong>手机实时画面</strong>
        <small>{{ resolutionLabel }}</small>
      </span>
      <span class="monitor-live" :class="isLive ? 'live' : 'paused'"><i />{{ isLive ? 'LIVE' : 'PAUSED' }}</span>
      <div class="monitor-actions" @pointerdown.stop>
        <button title="重新连接实时投屏" aria-label="重新连接实时投屏" :disabled="!deviceStore.connected" @click="retryStream">
          <RefreshCw :size="14" :class="{ spin: streamLoading }" />
        </button>
        <button title="隐藏手机画面" aria-label="隐藏手机画面" @click="hide"><EyeOff :size="14" /></button>
      </div>
    </header>

    <div class="device-monitor-stage">
      <canvas
        v-show="streamLive"
        ref="streamCanvas"
        class="monitor-canvas"
        width="1"
        height="1"
        role="img"
        aria-label="手机实时画面"
      />
      <div v-if="!deviceStore.connected" class="monitor-state">
        <WifiOff :size="25" />
        <strong>设备未连接</strong>
        <span>连接 Android 设备并授权 USB 调试后，这里会自动显示实时画面。</span>
        <button :disabled="deviceStore.checking" @click="checkDevice">
          <RefreshCw :size="13" :class="{ spin: deviceStore.checking }" />{{ deviceStore.checking ? '检测中' : '重新检测' }}
        </button>
      </div>
      <div v-else-if="streamError" class="monitor-state error">
        <WifiOff :size="25" />
        <strong>实时投屏已中断</strong>
        <span>{{ streamError }}</span>
        <button @click="retryStream"><RefreshCw :size="13" />立即重连</button>
      </div>
      <div v-else-if="streamLoading && !streamLive" class="monitor-state">
        <RefreshCw :size="24" class="spin" />
        <strong>正在启动低延迟投屏</strong>
        <span>首次连接会启动设备端 H.264 视频服务，通常需要 1–3 秒。</span>
      </div>
    </div>

    <footer class="device-monitor-footer">
      <span><i class="monitor-status-dot" :class="{ live: isLive, error: Boolean(streamError) }" />{{ statusLabel }}</span>
      <span>{{ streamLive ? 'H.264 · 实时' : '低延迟投屏' }}</span>
    </footer>

    <button
      class="monitor-resize-handle"
      title="拖动或使用方向键调整窗口大小"
      aria-label="调整窗口大小"
      @pointerdown="beginResize"
      @keydown="resizeByKeyboard"
    />
  </section>
</template>
