import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { deviceStreamUrl, fetchStreamStatus } from '../api/device.js'
import { useDeviceStream } from './useDeviceStream.js'

vi.mock('../api/device.js', () => ({
  deviceStreamUrl: vi.fn((token) => `/api/device/stream?stream=${token}`),
  fetchStreamStatus: vi.fn(),
}))

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
