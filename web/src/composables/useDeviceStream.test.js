import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { deviceStreamUrl, fetchStreamStatus } from '../api/device.js'
import { useDeviceStream } from './useDeviceStream.js'

vi.mock('../api/device.js', () => ({
  deviceStreamUrl: vi.fn((token) => `/api/device/stream?stream=${token}`),
  fetchStreamStatus: vi.fn(),
}))

const CONFIG = new Uint8Array([0, 0, 0, 1, 0x67, 0x42, 0, 0x1e, 0, 0, 0, 1, 0x68, 0xee])
const KEY = new Uint8Array([0, 0, 0, 1, 0x65, 0x88])
const DELTA = new Uint8Array([0, 0, 0, 1, 0x41, 0x88])
function session(width = 320, height = 240) {
  const data = new Uint8Array(12)
  const view = new DataView(data.buffer)
  view.setUint32(0, 0x80000000)
  view.setUint32(4, width)
  view.setUint32(8, height)
  return data
}
function packet(payload, flags = 0, pts = 0n) {
  const data = new Uint8Array(12 + payload.length)
  const view = new DataView(data.buffer)
  view.setUint32(0, flags | Number(pts >> 32n))
  view.setUint32(4, Number(pts & 0xffffffffn))
  view.setUint32(8, payload.length)
  data.set(payload, 12)
  return data
}
function join(...parts) {
  const data = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0))
  let offset = 0
  for (const part of parts) { data.set(part, offset); offset += part.length }
  return data
}
function webCodecs({ supported = true } = {}) {
  const decoders = []
  class Decoder {
    static isConfigSupported = vi.fn(async () => ({ supported }))
    constructor(callbacks) {
      this.callbacks = callbacks
      this.state = 'unconfigured'
      this.decodeQueueSize = 0
      this.decode = vi.fn()
      this.configure = vi.fn(() => { this.state = 'configured' })
      this.close = vi.fn(() => { this.state = 'closed' })
      decoders.push(this)
    }
  }
  vi.stubGlobal('VideoDecoder', Decoder)
  vi.stubGlobal('EncodedVideoChunk', class { constructor(init) { Object.assign(this, init) } })
  const paints = new Map()
  let paintId = 0
  vi.stubGlobal('requestAnimationFrame', vi.fn((callback) => { paints.set(++paintId, callback); return paintId }))
  vi.stubGlobal('cancelAnimationFrame', vi.fn((id) => paints.delete(id)))
  return { decoders, Decoder, paints }
}
function fetchStreams() {
  const streams = []
  vi.stubGlobal('fetch', vi.fn((_url, options) => {
    let controller
    const body = new ReadableStream({ start(c) { controller = c }, cancel: vi.fn() })
    streams.push({ controller, signal: options.signal })
    const h264 = options.headers.Accept === 'application/x-adb-h264'
    return Promise.resolve(new Response(body, { headers: { 'Content-Type': h264 ? 'application/x-adb-h264; version=1' : 'application/octet-stream' } }))
  }))
  return streams
}

let stream
const Host = defineComponent({
  setup() {
    stream = useDeviceStream({ reconnectDelay: 1500 })
    return () => h('div')
  },
})

function fakeCanvas() {
  const context = {
    clearRect: vi.fn(),
    drawImage: vi.fn(),
  }
  return {
    width: 1,
    height: 1,
    getContext: vi.fn(() => context),
    context,
  }
}

describe('useDeviceStream', () => {
  beforeEach(() => {
    vi.mocked(deviceStreamUrl).mockClear()
    vi.mocked(fetchStreamStatus).mockReset()
    vi.mocked(fetchStreamStatus).mockResolvedValue({ state: 'streaming', message: '' })
    vi.stubGlobal('createImageBitmap', vi.fn(async () => ({
      width: 324,
      height: 720,
      close: vi.fn(),
    })))
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('parses fragmented H264, probes SPS codec, normalizes PTS and releases frames on stop', async () => {
    const { decoders, Decoder, paints } = webCodecs()
    const connections = fetchStreams()
    const wrapper = mount(Host)
    stream.canvas.value = fakeCanvas()
    stream.start()
    await flushPromises()
    expect(deviceStreamUrl).toHaveBeenLastCalledWith(expect.any(String), 'h264')
    const wire = join(session(), packet(CONFIG, 0x40000000), packet(DELTA), packet(KEY, 0x20000000, 12345678901234567n), packet(DELTA, 0, 12345678901267900n))
    for (let i = 0; i < wire.length; i += 7) connections[0].controller.enqueue(wire.slice(i, i + 7))
    await flushPromises()
    expect(Decoder.isConfigSupported).toHaveBeenCalledWith({ codec: 'avc1.42001e', optimizeForLatency: true })
    expect(decoders[0].decode).toHaveBeenCalledTimes(2)
    expect(decoders[0].decode.mock.calls.map(([chunk]) => chunk.timestamp)).toEqual([0, 33333])
    expect(decoders[0].decode.mock.calls[0][0].type).toBe('key')
    const frame1 = { displayWidth: 320, displayHeight: 240, close: vi.fn() }
    const frame2 = { displayWidth: 640, displayHeight: 480, close: vi.fn() }
    decoders[0].callbacks.output(frame1)
    decoders[0].callbacks.output(frame2)
    expect(frame1.close).toHaveBeenCalledOnce()
    for (const callback of [...paints.values()]) callback()
    paints.clear()
    expect(frame2.close).toHaveBeenCalledOnce()
    expect(stream.canvas.value.width).toBe(640)
    expect(stream.live.value).toBe(true)
    const pending = { close: vi.fn() }
    decoders[0].callbacks.output(pending)
    stream.stop()
    expect(pending.close).toHaveBeenCalledOnce()
    expect(decoders[0].close).toHaveBeenCalledOnce()
    expect(connections[0].signal.aborted).toBe(true)
    expect(cancelAnimationFrame).toHaveBeenCalled()
    const late = { close: vi.fn() }
    decoders[0].callbacks.output(late)
    expect(late.close).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('falls back once for unsupported H264 and keeps JPEG on manual retry', async () => {
    webCodecs({ supported: false })
    const connections = fetchStreams()
    const wrapper = mount(Host)
    stream.start()
    await flushPromises()
    connections[0].controller.enqueue(join(session(), packet(CONFIG, 0x40000000)))
    await flushPromises()
    expect(globalThis.fetch).toHaveBeenCalledTimes(2)
    expect(connections[0].signal.aborted).toBe(true)
    expect(deviceStreamUrl).toHaveBeenLastCalledWith(expect.any(String), 'jpeg')
    stream.retry()
    await flushPromises()
    expect(deviceStreamUrl).toHaveBeenLastCalledWith(expect.any(String), 'jpeg')
    stream.stop()
    wrapper.unmount()
  })

  it('closes decoder on session changes and requires a fresh configuration and keyframe', async () => {
    const { decoders } = webCodecs()
    const connections = fetchStreams()
    const wrapper = mount(Host)
    stream.start()
    await flushPromises()
    connections[0].controller.enqueue(join(session(), packet(CONFIG, 0x40000000), packet(KEY, 0x20000000, 100n)))
    await flushPromises()
    connections[0].controller.enqueue(join(session(640, 480), packet(DELTA), packet(CONFIG, 0x40000000), packet(DELTA), packet(KEY, 0x20000000, 0n)))
    await flushPromises()
    expect(decoders[0].close).toHaveBeenCalledOnce()
    expect(decoders[1].decode).toHaveBeenCalledOnce()
    expect(decoders[1].decode.mock.calls[0][0].timestamp).toBe(0)
    stream.stop()
    wrapper.unmount()
  })

  it('falls back on asynchronous decoder error and on malformed protocol', async () => {
    const { decoders } = webCodecs()
    const connections = fetchStreams()
    const wrapper = mount(Host)
    stream.start()
    await flushPromises()
    connections[0].controller.enqueue(join(session(), packet(CONFIG, 0x40000000)))
    await flushPromises()
    decoders[0].callbacks.error(new Error('bad decoder'))
    await flushPromises()
    expect(deviceStreamUrl).toHaveBeenLastCalledWith(expect.any(String), 'jpeg')
    expect(decoders[0].close).toHaveBeenCalledOnce()
    stream.stop()
    wrapper.unmount()
  })

  it('reconnects after decode overload and eventually falls back instead of looping H264', async () => {
    vi.useFakeTimers()
    const { decoders } = webCodecs()
    const connections = fetchStreams()
    const wrapper = mount(Host)
    stream.start()
    await flushPromises()
    for (let attempt = 0; attempt < 3; attempt += 1) {
      connections[attempt].controller.enqueue(join(session(), packet(CONFIG, 0x40000000), packet(KEY, 0x20000000)))
      await flushPromises()
      decoders[attempt].decodeQueueSize = 6
      connections[attempt].controller.enqueue(packet(DELTA, 0, 1n))
      await flushPromises()
      await vi.advanceTimersByTimeAsync(40)
      expect(connections[attempt].signal.aborted).toBe(true)
      if (attempt < 2) await vi.advanceTimersByTimeAsync(1500 * 2 ** attempt)
    }
    expect(globalThis.fetch).toHaveBeenCalledTimes(4)
    expect(deviceStreamUrl).toHaveBeenLastCalledWith(expect.any(String), 'jpeg')
    stream.stop()
    wrapper.unmount()
  })

  it('lets a burst of cached GOP packets drain without unnecessary reconnection', async () => {
    vi.useFakeTimers()
    const { decoders } = webCodecs()
    const connections = fetchStreams()
    const wrapper = mount(Host)
    stream.start()
    await flushPromises()
    connections[0].controller.enqueue(join(session(), packet(CONFIG, 0x40000000), packet(KEY, 0x20000000)))
    await flushPromises()
    decoders[0].decodeQueueSize = 6
    connections[0].controller.enqueue(packet(DELTA, 0, 1n))
    await flushPromises()
    decoders[0].decodeQueueSize = 0
    await vi.advanceTimersByTimeAsync(40)
    expect(decoders[0].decode).toHaveBeenCalledTimes(2)
    expect(globalThis.fetch).toHaveBeenCalledTimes(1)
    stream.stop()
    wrapper.unmount()
  })

  it('does not allocate a decoder after a support probe resolves following stop', async () => {
    const { Decoder, decoders } = webCodecs()
    let resolveSupport
    Decoder.isConfigSupported.mockImplementation(() => new Promise((resolve) => { resolveSupport = resolve }))
    const connections = fetchStreams()
    const wrapper = mount(Host)
    stream.start()
    await flushPromises()
    connections[0].controller.enqueue(join(session(), packet(CONFIG, 0x40000000)))
    await flushPromises()
    stream.stop()
    resolveSupport({ supported: true })
    await flushPromises()
    expect(decoders).toHaveLength(0)
    wrapper.unmount()
  })

  it('decodes pushed frames and aborts the request when stopped', async () => {
    let streamController
    let requestSignal
    const fetchMock = vi.fn((_url, options) => {
      requestSignal = options.signal
      const body = new ReadableStream({
        start(controller) {
          streamController = controller
          options.signal.addEventListener('abort', () => {
            controller.error(new DOMException('Aborted', 'AbortError'))
          })
        },
      })
      return Promise.resolve(new Response(body, {
        status: 200,
        headers: { 'Content-Type': 'application/octet-stream' },
      }))
    })
    vi.stubGlobal('fetch', fetchMock)
    const canvas = fakeCanvas()
    const wrapper = mount(Host)
    stream.canvas.value = canvas

    stream.start()
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(stream.loading.value).toBe(true)

    streamController.enqueue(new Uint8Array([0, 0, 0, 4, 1, 2, 3, 4]))
    await vi.waitFor(() => expect(stream.live.value).toBe(true))
    expect(canvas.width).toBe(324)
    expect(canvas.height).toBe(720)
    expect(canvas.context.drawImage).toHaveBeenCalledTimes(1)
    expect(stream.loading.value).toBe(false)

    stream.stop()
    expect(requestSignal.aborted).toBe(true)
    expect(stream.live.value).toBe(false)
    expect(stream.error.value).toBe('')
    wrapper.unmount()
  })

  it('surfaces the backend reason for a failed start', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ detail: '找不到 scrcpy 投屏服务文件' }),
      { status: 503, headers: { 'Content-Type': 'application/json' } },
    )))
    const wrapper = mount(Host)

    stream.start()
    await flushPromises()

    expect(stream.error.value).toBe('找不到 scrcpy 投屏服务文件')
    expect(stream.live.value).toBe(false)
    expect(stream.loading.value).toBe(false)

    stream.stop()
    wrapper.unmount()
  })

  it('retries after a network failure and can retry manually', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn(async () => { throw new TypeError('Failed to fetch') })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(Host)

    stream.start()
    await vi.advanceTimersByTimeAsync(0)
    expect(stream.error.value).toBe('无法连接实时投屏服务')

    await vi.advanceTimersByTimeAsync(1499)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(fetchMock).toHaveBeenCalledTimes(2)

    stream.retry()
    expect(stream.error.value).toBe('')
    await vi.advanceTimersByTimeAsync(0)
    expect(fetchMock).toHaveBeenCalledTimes(3)

    stream.stop()
    wrapper.unmount()
  })
})
