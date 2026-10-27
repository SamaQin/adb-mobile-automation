import { onBeforeUnmount, ref } from 'vue'
import { deviceStreamUrl, fetchStreamStatus } from '../api/device.js'

const DEFAULT_RECONNECT_DELAY = 1500
const MAX_FRAME_BYTES = 16 * 1024 * 1024

function concatenate(left, right) {
  if (!left.length) return right
  const merged = new Uint8Array(left.length + right.length)
  merged.set(left)
  merged.set(right, left.length)
  return merged
}

async function responseError(response) {
  try {
    const payload = await response.json()
    if (typeof payload?.detail === 'string' && payload.detail.trim()) return payload.detail
  } catch {
    // Fall through to a status-based message.
  }
  return `投屏服务返回 ${response.status}`
}

export function useDeviceStream({ reconnectDelay = DEFAULT_RECONNECT_DELAY } = {}) {
  const canvas = ref(null)
  const loading = ref(false)
  const live = ref(false)
  const error = ref('')
  let active = false
  let generation = 0
  let retryCount = 0
  let retryTimer = null
  let controller = null
  let pendingFrame = null
  let frameWaiter = null
  let statusRequest = 0

  function clearRetry() {
    if (retryTimer != null) {
      window.clearTimeout(retryTimer)
      retryTimer = null
    }
  }

  function wakeRenderer() {
    if (frameWaiter) {
      const resolve = frameWaiter
      frameWaiter = null
      resolve()
    }
  }

  function resetConnection() {
    if (controller) {
      controller.abort()
      controller = null
    }
    pendingFrame = null
    wakeRenderer()
  }

  function clearCanvas() {
    const target = canvas.value
    if (!target) return
    const context = target.getContext('2d')
    context?.clearRect(0, 0, target.width, target.height)
  }

  function scheduleReconnect() {
    clearRetry()
    if (!active) return
    const delay = Math.min(reconnectDelay * 2 ** Math.min(retryCount, 2), 6000)
    retryCount += 1
    retryTimer = window.setTimeout(connect, delay)
  }

  async function describeError() {
    const request = ++statusRequest
    try {
      const status = await fetchStreamStatus()
      if (
        active
        && request === statusRequest
        && status?.state === 'error'
        && status.message
      ) {
        error.value = status.message
      }
    } catch {
      // Keep the generic stream error when status cannot be read.
    }
  }

  function fail(streamError, streamGeneration) {
    if (!active || streamGeneration !== generation) return
    if (streamError?.name === 'AbortError') return
    if (controller) {
      controller.abort()
      controller = null
    }
    loading.value = false
    live.value = false
    const message = streamError?.message === 'Failed to fetch'
      ? '无法连接实时投屏服务'
      : streamError?.message
    error.value = message || '实时投屏连接中断'
    generation += 1
    pendingFrame = null
    wakeRenderer()
    describeError()
    scheduleReconnect()
  }

  function drawFrame(frame, streamGeneration) {
    const target = canvas.value
    if (!target) return Promise.resolve()
    const blob = new Blob([frame], { type: 'image/jpeg' })
    return createImageBitmap(blob).then((bitmap) => {
      if (!active || streamGeneration !== generation) {
        bitmap.close()
        return
      }
      if (target.width !== bitmap.width || target.height !== bitmap.height) {
        target.width = bitmap.width
        target.height = bitmap.height
      }
      const context = target.getContext('2d')
      context?.drawImage(bitmap, 0, 0)
      bitmap.close()
      if (!live.value) {
        statusRequest += 1
        live.value = true
        loading.value = false
        error.value = ''
        retryCount = 0
      }
    })
  }

  async function renderFrames(streamGeneration) {
    while (active && streamGeneration === generation) {
      if (!pendingFrame) {
        await new Promise((resolve) => { frameWaiter = resolve })
        continue
      }
      const frame = pendingFrame
      pendingFrame = null
      await drawFrame(frame, streamGeneration)
    }
  }

  async function consume(response, streamGeneration, signal) {
    if (!response.body) throw new Error('当前浏览器不支持流式投屏')
    const reader = response.body.getReader()
    let buffer = new Uint8Array(0)
    void renderFrames(streamGeneration).catch((streamError) => {
      if (!signal.aborted) fail(streamError, streamGeneration)
    })
    while (active && streamGeneration === generation) {
      const result = await reader.read()
      if (result.done) break
      buffer = concatenate(buffer, result.value)
      while (buffer.length >= 4) {
        const size = new DataView(buffer.buffer, buffer.byteOffset, 4).getUint32(0)
        if (size <= 0 || size > MAX_FRAME_BYTES) {
          throw new Error('实时画面数据无效')
        }
        if (buffer.length < 4 + size) break
        const frame = buffer.slice(4, 4 + size)
        buffer = buffer.slice(4 + size)
        pendingFrame = frame
        wakeRenderer()
      }
    }
    if (active && streamGeneration === generation) {
      throw new Error('实时投屏连接已关闭')
    }
  }

  async function connect() {
    if (!active) return
    clearRetry()
    resetConnection()
    generation += 1
    statusRequest += 1
    const streamGeneration = generation
    loading.value = true
    live.value = false
    const currentController = new AbortController()
    controller = currentController
    try {
      const response = await fetch(
        deviceStreamUrl(`${Date.now()}-${streamGeneration}`),
        {
          cache: 'no-store',
          headers: { Accept: 'application/octet-stream' },
          signal: currentController.signal,
        },
      )
      if (!response.ok) throw new Error(await responseError(response))
      await consume(response, streamGeneration, currentController.signal)
    } catch (streamError) {
      fail(streamError, streamGeneration)
    }
  }

  function start() {
    if (active) return
    active = true
    retryCount = 0
    error.value = ''
    void connect()
  }

  function stop() {
    active = false
    generation += 1
    clearRetry()
    statusRequest += 1
    resetConnection()
    loading.value = false
    live.value = false
    error.value = ''
    clearCanvas()
  }

  function retry() {
    if (!active) return
    retryCount = 0
    error.value = ''
    void connect()
  }

  onBeforeUnmount(stop)

  return {
    canvas,
    loading,
    live,
    error,
    start,
    stop,
    retry,
  }
}
