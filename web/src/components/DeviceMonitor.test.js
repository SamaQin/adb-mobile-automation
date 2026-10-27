import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import DeviceMonitor from './DeviceMonitor.vue'
import PresetToolbar from './editors/PresetToolbar.vue'
import { useDeviceStore } from '../stores/deviceStore.js'
import { useUiStore } from '../stores/uiStore.js'
import { MONITOR_GEOMETRY_KEY } from '../utils/floatingWindow.js'

function mountWithPinia(component) {
  const pinia = createPinia()
  return {
    pinia,
    wrapper: mount(component, { global: { plugins: [pinia] } }),
  }
}

function createStorage() {
  const values = new Map()
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
    clear: () => values.clear(),
  }
}

describe('DeviceMonitor', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', createStorage())
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})))
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      clearRect: vi.fn(),
      drawImage: vi.fn(),
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('shows the disconnected state and can be hidden', async () => {
    const { pinia, wrapper } = mountWithPinia(DeviceMonitor)
    const deviceStore = useDeviceStore(pinia)

    expect(deviceStore.connected).toBe(false)
    expect(wrapper.text()).toContain('设备未连接')
    expect(wrapper.get('canvas').isVisible()).toBe(false)

    await wrapper.get('button[aria-label="隐藏手机画面"]').trigger('click')
    expect(wrapper.emitted('hide')).toHaveLength(1)

    wrapper.unmount()
  })

  it('starts the continuous stream when the device becomes available', async () => {
    const { pinia, wrapper } = mountWithPinia(DeviceMonitor)
    const deviceStore = useDeviceStore(pinia)

    deviceStore.connected = true
    deviceStore.resolution = { width: 1080, height: 2400 }
    await wrapper.vm.$nextTick()

    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringMatching(/^\/api\/device\/stream\?stream=/),
      expect.objectContaining({ cache: 'no-store' }),
    )
    expect(wrapper.text()).toContain('正在建立低延迟投屏')

    wrapper.unmount()
  })

  it('restores the last floating position and size', async () => {
    localStorage.setItem(MONITOR_GEOMETRY_KEY, JSON.stringify({
      x: 120,
      y: 80,
      width: 320,
      height: 480,
    }))
    const { wrapper } = mountWithPinia(DeviceMonitor)
    await wrapper.vm.$nextTick()

    expect(wrapper.element.style.left).toBe('120px')
    expect(wrapper.element.style.top).toBe('80px')
    expect(wrapper.element.style.width).toBe('320px')
    expect(wrapper.element.style.height).toBe('480px')

    wrapper.unmount()
  })

  it('toggles the monitor from the top toolbar', async () => {
    const { pinia, wrapper } = mountWithPinia(PresetToolbar)
    const uiStore = useUiStore(pinia)

    expect(uiStore.deviceMonitorOpen).toBe(false)
    await wrapper.get('.monitor-toggle').trigger('click')
    expect(uiStore.deviceMonitorOpen).toBe(true)
    expect(wrapper.get('.monitor-toggle').classes()).toContain('active')

    await wrapper.get('.monitor-toggle').trigger('click')
    expect(uiStore.deviceMonitorOpen).toBe(false)

    wrapper.unmount()
  })
})
