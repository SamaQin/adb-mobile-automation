import { onBeforeUnmount, ref } from 'vue'
import { deviceStreamUrl, fetchStreamStatus } from '../api/device.js'

const MAX_FRAME_BYTES = 16 * 1024 * 1024
const MAX_DECODE_QUEUE = 6

function concatenate(left, right) {
  if (!left.length) return right
  const merged = new Uint8Array(left.length + right.length)
  merged.set(left)
  merged.set(right, left.length)
  return merged
}

// Annex-B is used throughout: WebCodecs derives its AVC configuration from SPS/PPS.
export function h264Codec(config) {
  for (let i = 0; i + 6 < config.length; i += 1) {
    const prefix = config[i] === 0 && config[i + 1] === 0
      ? (config[i + 2] === 1 ? 3 : config[i + 2] === 0 && config[i + 3] === 1 ? 4 : 0)
      : 0
    if (prefix && (config[i + prefix] & 31) === 7 && i + prefix + 3 < config.length) {
      return `avc1.${Array.from(config.slice(i + prefix + 1, i + prefix + 4), (v) => v.toString(16).padStart(2, '0')).join('')}`
    }
  }
  throw new Error('H.264 SPS 配置无效')
}

async function responseError(response) {
  try {
    const payload = await response.json()
    if (typeof payload?.detail === 'string' && payload.detail.trim()) return payload.detail
  } catch { /* Use the HTTP status if there is no JSON detail. */ }
  return `投屏服务返回 ${response.status}`
}

export function useDeviceStream({ reconnectDelay = 1500 } = {}) {
  const canvas = ref(null)
  const loading = ref(false)
  const live = ref(false)
  const error = ref('')
  const codec = ref('jpeg')
  let active = false
  let generation = 0
  let retryCount = 0
  let retryTimer = null
  let connection = null
  let statusRequest = 0
  let h264Disabled = false
  let overloads = 0

  const current = (ctx) => active && connection === ctx && ctx.generation === generation

  function clearRetry() {
    if (retryTimer != null) window.clearTimeout(retryTimer)
    retryTimer = null
  }

  function closeDecoder(ctx) {
    ctx.decoderEpoch += 1
    if (ctx.decoder && ctx.decoder.state !== 'closed') ctx.decoder.close()
    ctx.decoder = null
    ctx.pendingVideo?.close()
    ctx.pendingVideo = null
    if (ctx.raf != null) window.cancelAnimationFrame(ctx.raf)
    ctx.raf = null
  }

  function resetConnection() {
    const ctx = connection
    connection = null
    if (!ctx) return
    ctx.controller.abort()
    void ctx.reader?.cancel().catch(() => {})
    closeDecoder(ctx)
    ctx.pendingJpeg = null
    window.clearTimeout(ctx.decodeYieldTimer)
    ctx.decodeYieldResolve?.()
    window.clearTimeout(ctx.firstFrameTimer)
  }

  function clearCanvas() {
    const target = canvas.value
    target?.getContext('2d')?.clearRect(0, 0, target.width, target.height)
  }

  function markLive(ctx) {
    if (!current(ctx)) return
    window.clearTimeout(ctx.firstFrameTimer)
    statusRequest += 1
    live.value = true
    loading.value = false
    error.value = ''
    retryCount = 0
  }

  function draw(image, ctx) {
    if (!current(ctx) || !canvas.value) return
    const target = canvas.value
    const width = image.displayWidth || image.width
    const height = image.displayHeight || image.height
    if (target.width !== width || target.height !== height) {
      target.width = width
      target.height = height
    }
    target.getContext('2d')?.drawImage(image, 0, 0)
    markLive(ctx)
  }

  async function renderJpeg(ctx) {
    if (ctx.rendering) return
    ctx.rendering = true
    try {
      while (current(ctx) && ctx.pendingJpeg) {
        const bytes = ctx.pendingJpeg
        ctx.pendingJpeg = null
        const bitmap = await createImageBitmap(new Blob([bytes], { type: 'image/jpeg' }))
        try { draw(bitmap, ctx) } finally { bitmap.close() }
      }
    } catch (err) {
      fail(err, ctx)
    } finally {
      ctx.rendering = false
    }
  }

  function outputVideo(frame, ctx, epoch) {
    if (!current(ctx) || epoch !== ctx.decoderEpoch) {
      frame.close()
      return
    }
    // Decoded frames are independent; keep only the newest one for the next paint.
    ctx.pendingVideo?.close()
    ctx.pendingVideo = frame
    if (ctx.raf != null) return
    ctx.raf = window.requestAnimationFrame(() => {
      ctx.raf = null
      const latest = ctx.pendingVideo
      ctx.pendingVideo = null
      if (!latest) return
      try { draw(latest, ctx) } catch (err) { fail(err, ctx) } finally { latest.close() }
    })
  }

  async function configureDecoder(ctx, config) {
    closeDecoder(ctx)
    const settings = { codec: h264Codec(config), optimizeForLatency: true }
    const support = await VideoDecoder.isConfigSupported(settings)
    if (!current(ctx)) return
    if (!support.supported) throw new Error('当前浏览器不支持此 H.264 编码')
    const epoch = ctx.decoderEpoch
    ctx.decoder = new VideoDecoder({
      output: (frame) => outputVideo(frame, ctx, epoch),
      error: (err) => { if (epoch === ctx.decoderEpoch) fail(err, ctx) },
    })
    ctx.decoder.configure(settings)
    ctx.config = config
    ctx.waitingKey = true
    ctx.basePts = null
    ctx.lastPts = null
  }

  async function h264Packet(ctx, high, low, payload) {
    if (high & 0x40000000) {
      await configureDecoder(ctx, payload)
      return
    }
    const key = Boolean(high & 0x20000000)
    if (!ctx.decoder || (ctx.waitingKey && !key)) return
    const pts = (BigInt(high & 0x1fffffff) << 32n) | BigInt(low)
    if (ctx.lastPts !== null && pts < ctx.lastPts) {
      // A new encoder timebase needs a fresh keyframe and decoder.
      if (!key) throw new Error('H.264 时间戳倒退')
      await configureDecoder(ctx, ctx.config)
      if (!current(ctx)) return
    }
    if (ctx.decoder.decodeQueueSize >= MAX_DECODE_QUEUE) {
      // A cached GOP may arrive in one fetch chunk. Yield to decoder tasks once
      // before treating a sustained queue as overload; never drop delta chunks.
      await new Promise((resolve) => {
        ctx.decodeYieldResolve = resolve
        ctx.decodeYieldTimer = window.setTimeout(resolve, 40)
      })
      ctx.decodeYieldResolve = null
      ctx.decodeYieldTimer = null
      if (!current(ctx)) return
    }
    if (ctx.decoder.decodeQueueSize >= MAX_DECODE_QUEUE) {
      const err = new Error('H.264 解码队列过载，等待关键帧重新同步')
      err.resync = true
      throw err
    }
    if (ctx.basePts === null) ctx.basePts = pts
    const timestamp = Number(pts - ctx.basePts)
    if (!Number.isSafeInteger(timestamp)) throw new Error('H.264 时间戳无效')
    ctx.decoder.decode(new EncodedVideoChunk({ type: key ? 'key' : 'delta', timestamp, data: key ? concatenate(ctx.config, payload) : payload }))
    ctx.waitingKey = false
    ctx.lastPts = pts
  }

  async function consume(response, ctx) {
    if (!response.body) throw new Error('当前浏览器不支持流式投屏')
    const reader = response.body.getReader()
    ctx.reader = reader
    let buffer = new Uint8Array(0)
    try {
      while (current(ctx)) {
        const result = await reader.read()
        if (!current(ctx)) return
        if (result.done) break
        buffer = concatenate(buffer, result.value)
        const headerSize = ctx.codec === 'h264' ? 12 : 4
        while (current(ctx) && buffer.length >= headerSize) {
          const view = new DataView(buffer.buffer, buffer.byteOffset, headerSize)
          const high = view.getUint32(0)
          if (ctx.codec === 'h264' && (high & 0x80000000)) {
            const width = view.getUint32(4)
            const height = view.getUint32(8)
            if (!width || !height || width > 16384 || height > 16384) throw new Error('投屏分辨率无效')
            closeDecoder(ctx)
            ctx.config = null
            ctx.waitingKey = true
            buffer = buffer.slice(12)
            continue
          }
          const size = ctx.codec === 'h264' ? view.getUint32(8) : high
          if (!size || size > MAX_FRAME_BYTES) throw new Error('实时画面数据无效')
          if (buffer.length < headerSize + size) break
          const payload = buffer.slice(headerSize, headerSize + size)
          const low = ctx.codec === 'h264' ? view.getUint32(4) : 0
          buffer = buffer.slice(headerSize + size)
          if (ctx.codec === 'h264') await h264Packet(ctx, high, low, payload)
          else {
            ctx.pendingJpeg = payload
            void renderJpeg(ctx)
          }
        }
      }
      if (current(ctx)) throw new Error('实时投屏连接已关闭')
    } finally {
      // Always release the stream reader, including stale/aborted connections.
      await reader.cancel().catch(() => {})
      reader.releaseLock()
      if (ctx.reader === reader) ctx.reader = null
    }
  }

  async function describeError() {
    const request = ++statusRequest
    try {
      const status = await fetchStreamStatus()
      if (active && request === statusRequest && status?.state === 'error' && status.message) error.value = status.message
    } catch { /* Keep the connection error if status is unavailable. */ }
  }

  function fail(err, ctx) {
    if (!current(ctx) || err?.name === 'AbortError') return
    const fallback = ctx.codec === 'h264' && (!err?.resync || ++overloads > 2)
    if (fallback) h264Disabled = true
    generation += 1
    resetConnection()
    loading.value = fallback
    live.value = false
    if (fallback) {
      error.value = ''
      void connect()
      return
    }
    error.value = err?.message === 'Failed to fetch' ? '无法连接实时投屏服务' : err?.message || '实时投屏连接中断'
    void describeError()
    clearRetry()
    const delay = Math.min(reconnectDelay * 2 ** Math.min(retryCount++, 2), 6000)
    retryTimer = window.setTimeout(connect, delay)
  }

  async function connect() {
    if (!active) return
    clearRetry()
    resetConnection()
    generation += 1
    statusRequest += 1
    const supportsWebCodecs = typeof VideoDecoder !== 'undefined'
      && typeof VideoDecoder.isConfigSupported === 'function' && typeof EncodedVideoChunk !== 'undefined'
    codec.value = !h264Disabled && supportsWebCodecs ? 'h264' : 'jpeg'
    const ctx = {
      generation, codec: codec.value, controller: new AbortController(), decoder: null,
      decoderEpoch: 0, pendingVideo: null, raf: null, pendingJpeg: null, reader: null,
      waitingKey: true, config: null, basePts: null, lastPts: null,
    }
    connection = ctx
    loading.value = true
    live.value = false
    if (ctx.codec === 'h264') {
      ctx.firstFrameTimer = window.setTimeout(() => fail(new Error('H.264 首帧等待超时'), ctx), 10000)
    }
    try {
      const response = await fetch(deviceStreamUrl(`${Date.now()}-${generation}`, ctx.codec), {
        cache: 'no-store', headers: { Accept: ctx.codec === 'h264' ? 'application/x-adb-h264' : 'application/octet-stream' },
        signal: ctx.controller.signal,
      })
      if (!current(ctx)) {
        void response.body?.cancel().catch(() => {})
        return
      }
      if (!response.ok) throw new Error(await responseError(response))
      if (ctx.codec === 'h264' && !response.headers.get('Content-Type')?.includes('application/x-adb-h264')) {
        void response.body?.cancel().catch(() => {})
        throw new Error('投屏服务不支持 H.264 直传')
      }
      await consume(response, ctx)
    } catch (err) { fail(err, ctx) }
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
  return { canvas, loading, live, error, codec, start, stop, retry }
}
