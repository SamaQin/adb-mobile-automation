import { shallowMount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import StepFormPanel from './StepFormPanel.vue'
import { useConfigStore } from '../../stores/configStore.js'
import { useUiStore } from '../../stores/uiStore.js'
import { useHistoryStore } from '../../stores/historyStore.js'
import { useDeviceStore } from '../../stores/deviceStore.js'
import { useRunStore } from '../../stores/runStore.js'
import TemplatePicker from './TemplatePicker.vue'

beforeEach(() => {
  setActivePinia(createPinia())
  useDeviceStore().connected = true
})

function setup(fields, params = {}, kind = 'find_and_tap') {
  const config = useConfigStore()
  config.config = { selected_preset_id: 'p', presets: [{ id: 'p', name: 'p', steps: [{ id: 'a', kind, name: 'a', enabled: true, on_failure: 'stop', params }] }] }
  config.definitions = [{ key: kind, can_fail: true, fields }]
  return { config, wrapper: shallowMount(StepFormPanel, { props: { nodeId: 'a' } }) }
}

it('shows ROI fields only when enabled and restores device-pixel rectangles in one edit', async () => {
  const config = useConfigStore()
  config.config = { selected_preset_id: 'p', presets: [{ id: 'p', name: 'p', steps: [{ id: 'a', kind: 'find_and_tap', name: 'a', enabled: true, on_failure: 'stop', params: { roi_enabled: false } }] }] }
  config.definitions = [{ key: 'find_and_tap', fields: [
    { key: 'roi_enabled', label: '限制识别区域', kind: 'bool', default: false },
    ...['search_x', 'search_y', 'search_width', 'search_height'].map((key, index) => ({ key, label: key, kind: 'int', default: 0, coordinate_axis: index % 2 ? 'y' : 'x' })),
  ] }]
  const wrapper = shallowMount(StepFormPanel, { props: { nodeId: 'a' } })
  expect(wrapper.findAll('.coordinate-group')).toHaveLength(0)
  config.selectedPreset.steps[0].params.roi_enabled = true
  await flushPromises()
  expect(wrapper.findAll('.coordinate-group')).toHaveLength(1)
  await wrapper.find('.coordinate-group-picker').trigger('click')
  const ui = useUiStore()
  expect(ui.screenshotRequest.mode).toBe('rect')
  ui.closeScreenshot({ x: 210, y: 130, width: 400, height: 300, resolution: { width: 1080, height: 1920 } })
  await flushPromises()
  expect(config.selectedPreset.steps[0].params).toMatchObject({ search_x: 210, search_y: 130, search_width: 400, search_height: 300 })
  expect(config.selectedPreset.steps[0].screen_resolution).toEqual({ width: 1080, height: 1920 })
  expect(useHistoryStore().undoStack).toHaveLength(1)
  wrapper.unmount()
})

it('renders the recording field for recorded action steps', () => {
  const { wrapper } = setup(
    [{ key: 'actions', label: '操作序列', kind: 'recording', default: [] }],
    { actions: [] },
    'recorded_actions',
  )
  expect(wrapper.find('.recording-field').exists()).toBe(true)
  wrapper.unmount()
})

it('groups recognition controls and reveals saved inactive settings without showing disabled coordinates', async () => {
  const { wrapper } = setup([
    { key: 'templates', kind: 'templates', default: [] },
    { key: 'require_all', label: '匹配模式', kind: 'bool', default: false },
    { key: 'tap_between', label: '重试前点击', kind: 'bool', default: false },
    { key: 'tap_between_x', label: '点击 X', kind: 'int', default: 540, coordinate_axis: 'x' },
    { key: 'swipe_between', label: '重试前滑动', kind: 'bool', default: false },
    { key: 'x1', label: '滑动起点 X', kind: 'int', default: 540, coordinate_axis: 'x' },
    { key: 'duration', label: '时长', kind: 'int', default: 300 },
    { key: 'offset_x', label: '点击偏移 X', kind: 'int', default: 0, coordinate_axis: 'x', coordinate_offset: true },
  ], { tap_between: false, swipe_between: false, tap_between_x: 200, offset_x: -12 })
  expect(wrapper.find('[data-group="core"]').text()).toContain('所有模板都匹配才算成功')
  expect(wrapper.find('[name="tap_between_x"]').exists()).toBe(false)
  expect(wrapper.find('[name="x1"]').exists()).toBe(false)
  expect(wrapper.find('[name="duration"]').exists()).toBe(false)
  expect(wrapper.find('[data-group="retry"]').attributes('open')).toBeDefined()
  expect(wrapper.find('[data-group="retry"]').text()).toContain('点击 X = 200')
  expect(wrapper.find('[data-group="advanced"]').attributes('open')).toBeDefined()
  await wrapper.find('[name="tap_between"]').setValue(true)
  await wrapper.find('[name="swipe_between"]').setValue(true)
  expect(wrapper.find('[name="tap_between_x"]').exists()).toBe(true)
  expect(wrapper.find('[name="x1"]').exists()).toBe(true)
  expect(wrapper.find('[name="duration"]').exists()).toBe(true)
  wrapper.unmount()
})

it('collapses default retry actions and advanced offsets', () => {
  const { wrapper } = setup([
    { key: 'templates', kind: 'templates', default: [] },
    { key: 'tap_between', label: '重试前点击', kind: 'bool', default: false },
    { key: 'offset_x', label: '偏移', kind: 'int', default: 0, coordinate_offset: true },
  ])
  expect(wrapper.find('[data-group="retry"]').attributes('open')).toBeUndefined()
  expect(wrapper.find('[data-group="advanced"]').attributes('open')).toBeUndefined()
  wrapper.unmount()
})

it('rejects empty, fractional, non-finite and out-of-range numbers without committing and recovers on input', async () => {
  const { config, wrapper } = setup([
    { key: 'attempts', label: '识别次数', kind: 'int', default: 1, min: 0, max: 10 },
    { key: 'interval', label: '间隔', kind: 'float', default: 1 },
    { key: 'offset_x', label: '偏移', kind: 'int', default: 0, coordinate_offset: true },
  ], { attempts: 1, interval: 1 }, 'tap')
  const input = wrapper.find('[name="attempts"]')
  for (const value of ['', '2.5', '-1', '11', '1e999']) {
    await input.setValue(value)
    expect(input.attributes('aria-invalid')).toBe('true')
    expect(config.selectedPreset.steps[0].params.attempts).toBe(1)
  }
  expect(useHistoryStore().undoStack).toHaveLength(0)
  input.element.value = '0'
  await input.trigger('input')
  expect(input.attributes('aria-invalid')).toBe('false')
  await input.trigger('change')
  expect(config.selectedPreset.steps[0].params.attempts).toBe(0)
  await wrapper.find('[name="interval"]').setValue('-0.5')
  expect(config.selectedPreset.steps[0].params.interval).toBe(1)
  await wrapper.find('[name="offset_x"]').setValue('-20')
  expect(config.selectedPreset.steps[0].params.offset_x).toBe(-20)
  wrapper.unmount()
})

it('honors FieldSpec minimum and maximum and rejects zero-size ROI', async () => {
  const { config, wrapper } = setup([
    { key: 'roi_enabled', kind: 'bool', default: true },
    { key: 'search_width', label: '宽度', kind: 'int', default: 20, coordinate_axis: 'x' },
    { key: 'seconds', label: '秒', kind: 'float', default: 1, minimum: 0.5, maximum: 2 },
  ], { roi_enabled: true, search_width: 20, seconds: 1 })
  await wrapper.find('[name="search_width"]').setValue('0')
  await wrapper.find('[name="seconds"]').setValue('0.2')
  expect(config.selectedPreset.steps[0].params).toMatchObject({ search_width: 20, seconds: 1 })
  expect(wrapper.findAll('[aria-invalid="true"]')).toHaveLength(2)
  await wrapper.find('[name="seconds"]').setValue('1.5')
  expect(config.selectedPreset.steps[0].params.seconds).toBe(1.5)
  wrapper.unmount()
})

it('checks disconnected devices and gives an actionable message without opening screenshot selection', async () => {
  const { wrapper } = setup([{ key: 'x', label: 'X', kind: 'int', default: 0, coordinate_axis: 'x' }], {}, 'tap')
  const device = useDeviceStore()
  device.connected = false
  vi.spyOn(device, 'check').mockResolvedValue(false)
  await wrapper.find('.coordinate-group-picker').trigger('click')
  await flushPromises()
  expect(device.check).toHaveBeenCalledOnce()
  expect(useUiStore().screenshotRequest).toBeNull()
  expect(useUiStore().toast.message).toContain('设备未连接')
  wrapper.unmount()
})

it.each(['point', 'swipe'])('preserves %s screenshot coordinates in original device pixels', async (mode) => {
  const keys = mode === 'point' ? ['x', 'y'] : ['x1', 'y1', 'x2', 'y2']
  const fields = keys.map((key, index) => ({ key, label: key, kind: 'int', default: 0, coordinate_axis: index % 2 ? 'y' : 'x' }))
  const { config, wrapper } = setup(fields, {}, mode === 'point' ? 'tap' : 'swipe')
  await wrapper.find('.coordinate-group-picker').trigger('click')
  await flushPromises()
  const ui = useUiStore()
  expect(ui.screenshotRequest.mode).toBe(mode)
  const result = mode === 'point' ? { x: 200, y: 400 } : { x1: 100, y1: 200, x2: 600, y2: 800 }
  ui.closeScreenshot({ ...result, resolution: { width: 1080, height: 1920 } })
  await flushPromises()
  expect(config.selectedPreset.steps[0].params).toMatchObject(result)
  expect(useHistoryStore().undoStack).toHaveLength(1)
  wrapper.unmount()
})

it('guards template thresholds at the commit boundary and clears the error after correction', async () => {
  const { config, wrapper } = setup([{ key: 'templates', kind: 'templates', default: [] }], { templates: [] })
  const picker = wrapper.findComponent(TemplatePicker)
  picker.vm.$emit('update:modelValue', [{ file: 'target.png', threshold: NaN }])
  await flushPromises()
  expect(config.selectedPreset.steps[0].params.templates).toEqual([])
  expect(wrapper.find('.field-error').text()).toContain('0 到 1')
  picker.vm.$emit('update:modelValue', [{ file: 'target.png', threshold: 0.8 }])
  await flushPromises()
  expect(config.selectedPreset.steps[0].params.templates[0].threshold).toBe(0.8)
  expect(wrapper.find('.field-error').exists()).toBe(false)
  wrapper.unmount()
})

it('explains why edits and screenshot selection are unavailable during a run or in read-only mode', async () => {
  const { wrapper } = setup([{ key: 'x', label: 'X', kind: 'int', default: 0, coordinate_axis: 'x' }], {}, 'tap')
  useRunStore().state = 'running'
  await flushPromises()
  expect(wrapper.find('[role="status"]').text()).toContain('运行中')
  expect(wrapper.find('.coordinate-group-picker').attributes('disabled')).toBeDefined()
  useRunStore().state = 'idle'
  useUiStore().readOnly = true
  await flushPromises()
  expect(wrapper.find('[role="status"]').text()).toContain('只读')
  wrapper.unmount()
})
