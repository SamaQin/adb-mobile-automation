<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Check, Crosshair, Image, MousePointer2, RefreshCw, X, ZoomIn, ZoomOut } from 'lucide-vue-next'
import { fetchScreenshot } from '../../api/device.js'
import { displayToRaw, fitTransform, rawRectFromDisplay } from '../../composables/useScreenshotEditor.js'

const props = defineProps({ request: { type: Object, required: true } })
const emit = defineEmits(['close'])
const canvas = ref(null)
const wrap = ref(null)
const image = ref(null)
const objectUrl = ref('')
const loading = ref(false)
const error = ref('')
const zoom = ref(1)
const start = ref(null)
const current = ref(null)
const dragging = ref(false)
const point = ref(null)
const imageSize = computed(() => ({ width: image.value?.naturalWidth || 1, height: image.value?.naturalHeight || 1 }))
const modeLabel = computed(() => ({ point: '点选坐标', rect: '框选区域', swipe: '拖动滑动轨迹' })[props.request.mode] || '选择')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const blob = await fetchScreenshot()
    if (objectUrl.value) URL.revokeObjectURL(objectUrl.value)
    objectUrl.value = URL.createObjectURL(blob)
    const next = new window.Image()
    next.onload = () => { image.value = next; nextTick(draw) }
    next.onerror = () => { error.value = '无法解码设备截图' }
    next.src = objectUrl.value
  } catch (loadError) {
    error.value = loadError.message
  } finally {
    loading.value = false
  }
}

function resizeCanvas() {
  if (!canvas.value || !wrap.value) return
  const rect = wrap.value.getBoundingClientRect()
  canvas.value.width = Math.max(1, Math.floor(rect.width))
  canvas.value.height = Math.max(1, Math.floor(rect.height))
  draw()
}

function transform() {
  return fitTransform({ width: canvas.value.width, height: canvas.value.height }, imageSize.value, zoom.value)
}

function draw() {
  const target = canvas.value
  if (!target) return
  const context = target.getContext('2d')
  context.clearRect(0, 0, target.width, target.height)
  context.fillStyle = '#060b12'
  context.fillRect(0, 0, target.width, target.height)
  if (!image.value) return
  const view = transform()
  context.drawImage(image.value, view.offsetX, view.offsetY, imageSize.value.width * view.scale, imageSize.value.height * view.scale)

  const a = start.value || point.value
  const b = current.value || point.value
  if (!a || !b) return
  context.save()
  context.strokeStyle = '#38bdf8'
  context.fillStyle = 'rgba(56, 189, 248, 0.15)'
  context.lineWidth = 2
  context.setLineDash(props.request.mode === 'swipe' ? [8, 5] : [])
  if (props.request.mode === 'point') {
    context.beginPath(); context.moveTo(a.x - 16, a.y); context.lineTo(a.x + 16, a.y); context.moveTo(a.x, a.y - 16); context.lineTo(a.x, a.y + 16); context.stroke()
    context.beginPath(); context.arc(a.x, a.y, 4, 0, Math.PI * 2); context.fill()
  } else if (props.request.mode === 'rect') {
    context.fillRect(Math.min(a.x, b.x), Math.min(a.y, b.y), Math.abs(b.x - a.x), Math.abs(b.y - a.y))
    context.strokeRect(Math.min(a.x, b.x), Math.min(a.y, b.y), Math.abs(b.x - a.x), Math.abs(b.y - a.y))
  } else {
    context.beginPath(); context.moveTo(a.x, a.y); context.lineTo(b.x, b.y); context.stroke()
    const angle = Math.atan2(b.y - a.y, b.x - a.x)
    context.setLineDash([]); context.beginPath(); context.moveTo(b.x, b.y); context.lineTo(b.x - 13 * Math.cos(angle - 0.5), b.y - 13 * Math.sin(angle - 0.5)); context.lineTo(b.x - 13 * Math.cos(angle + 0.5), b.y - 13 * Math.sin(angle + 0.5)); context.closePath(); context.fill()
  }
  context.restore()
}

function canvasPoint(event) {
  const rect = canvas.value.getBoundingClientRect()
  return { x: event.clientX - rect.left, y: event.clientY - rect.top }
}

function pointerDown(event) {
  if (!image.value) return
  const value = canvasPoint(event)
  if (props.request.mode === 'point') {
    point.value = value
    start.value = value
    current.value = value
    draw()
    return
  }
  dragging.value = true
  start.value = value
  current.value = value
  canvas.value.setPointerCapture(event.pointerId)
  draw()
}

function pointerMove(event) {
  if (!dragging.value) return
  current.value = canvasPoint(event)
  draw()
}

function pointerUp(event) {
  if (!dragging.value) return
  current.value = canvasPoint(event)
  dragging.value = false
  draw()
}

function wheel(event) {
  event.preventDefault()
  zoom.value = Math.max(0.5, Math.min(3, zoom.value + (event.deltaY < 0 ? 0.1 : -0.1)))
  draw()
}

function result() {
  if (!start.value) return null
  const view = transform()
  const resolution = { width: imageSize.value.width, height: imageSize.value.height }
  if (props.request.mode === 'point') return { ...displayToRaw(start.value, view, imageSize.value), resolution }
  if (!current.value) return null
  if (props.request.mode === 'rect') return { ...rawRectFromDisplay(start.value, current.value, view, imageSize.value), resolution }
  const a = displayToRaw(start.value, view, imageSize.value)
  const b = displayToRaw(current.value, view, imageSize.value)
  return { x1: a.x, y1: a.y, x2: b.x, y2: b.y, resolution }
}

function keydown(event) {
  if (event.key === 'Escape') emit('close', null)
  if (event.key === 'Enter' && result()) emit('close', result())
}

const observer = new ResizeObserver(resizeCanvas)
onMounted(() => { observer.observe(wrap.value); window.addEventListener('keydown', keydown); load() })
onBeforeUnmount(() => { observer.disconnect(); window.removeEventListener('keydown', keydown); if (objectUrl.value) URL.revokeObjectURL(objectUrl.value) })
watch(zoom, draw)
</script>

<template>
  <div class="modal-backdrop" @mousedown.self="emit('close', null)">
    <section class="screenshot-modal panel" role="dialog" aria-modal="true" :aria-label="request.title || modeLabel">
      <header><div><Crosshair :size="18" /><span><strong>{{ request.title || '截图编辑器' }}</strong><small>{{ modeLabel }} · {{ imageSize.width }}×{{ imageSize.height }}</small></span></div><button class="icon-button" title="关闭" @click="emit('close', null)"><X :size="17" /></button></header>
      <div class="screenshot-tools"><button title="刷新截图" :disabled="loading" @click="load"><RefreshCw :size="15" /></button><button title="缩小" @click="zoom = Math.max(0.5, zoom - 0.1)"><ZoomOut :size="15" /></button><span>{{ Math.round(zoom * 100) }}%</span><button title="放大" @click="zoom = Math.min(3, zoom + 0.1)"><ZoomIn :size="15" /></button><div /><span v-if="result()" class="coordinate-readout">{{ JSON.stringify(result()).replace(/\{"|"\}/g, '').replaceAll('"', '').replaceAll(',', ' · ') }}</span></div>
      <div ref="wrap" class="screenshot-stage"><canvas ref="canvas" @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="pointerUp" @wheel="wheel" /><div v-if="loading" class="stage-state"><RefreshCw :size="24" class="spin" />正在获取截图</div><div v-else-if="error" class="stage-state error"><Image :size="24" />{{ error }}</div><div v-else-if="!image" class="stage-state"><MousePointer2 :size="24" />等待截图</div></div>
      <footer><button @click="emit('close', null)">取消</button><button class="primary" :disabled="!result()" @click="emit('close', result())"><Check :size="15" />确认选择</button></footer>
    </section>
  </div>
</template>
