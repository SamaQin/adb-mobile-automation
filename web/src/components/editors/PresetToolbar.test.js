import { shallowMount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import PresetToolbar from './PresetToolbar.vue'
import { useConfigStore } from '../../stores/configStore.js'
import { useDeviceStore } from '../../stores/deviceStore.js'
import { useRunStore } from '../../stores/runStore.js'

beforeEach(() => setActivePinia(createPinia()))

it('checks the device once before saving a draft and ignores repeated run clicks', async () => {
  const config = useConfigStore()
  config.config = { acceleration: 'cpu', selected_preset_id: 'p', presets: [{ id: 'p', name: 'p', loop_count: 1, steps: [{ id: 'a', enabled: true, params: {} }] }] }
  config.dirty = true
  const device = useDeviceStore()
  const run = useRunStore()
  let resolve
  const check = vi.spyOn(device, 'check').mockImplementation(() => new Promise((done) => { resolve = done }))
  const save = vi.spyOn(config, 'save').mockResolvedValue()
  vi.spyOn(config, 'applyScreenResolution').mockImplementation(() => {})
  const start = vi.spyOn(run, 'start').mockResolvedValue()
  const wrapper = shallowMount(PresetToolbar)
  const button = wrapper.find('[title="运行当前预设"]')
  await button.trigger('click')
  await button.trigger('click')
  expect(check).toHaveBeenCalledTimes(1)
  expect(button.attributes('disabled')).toBeDefined()
  device.resolution = { width: 100, height: 60 }
  resolve(true)
  await flushPromises()
  expect(save).toHaveBeenCalledTimes(1)
  expect(start).toHaveBeenCalledExactlyOnceWith('p')
  expect(check).toHaveBeenCalledTimes(1)
  expect(button.attributes('disabled')).toBeUndefined()
  wrapper.unmount()
})
