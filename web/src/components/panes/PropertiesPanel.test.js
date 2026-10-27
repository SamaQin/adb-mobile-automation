import { shallowMount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it } from 'vitest'
import PropertiesPanel from './PropertiesPanel.vue'
import { useConfigStore } from '../../stores/configStore.js'
import { useRunStore } from '../../stores/runStore.js'
import { useUiStore } from '../../stores/uiStore.js'

beforeEach(() => {
  setActivePinia(createPinia())
  useConfigStore().config = { selected_preset_id: 'p', presets: [{ id: 'p', name: '示例预设', loop_count: 1, steps: [{ id: 'a', name: '识别', params: {} }] }] }
})

it('guides empty selection and explains how to build a flow', () => {
  const wrapper = shallowMount(PropertiesPanel)
  expect(wrapper.text()).toContain('选择节点编辑')
  expect(wrapper.text()).toContain('Shift')
  expect(wrapper.text()).toContain('前置依赖')
  wrapper.unmount()
})

it('starts each selected step at the top of its inspector', async () => {
  const ui = useUiStore()
  const wrapper = shallowMount(PropertiesPanel)
  wrapper.find('.properties-scroll').element.scrollTop = 250
  ui.selectedNodeIds = ['a']
  await flushPromises()
  expect(wrapper.find('.properties-scroll').element.scrollTop).toBe(0)
  wrapper.unmount()
})

it('shows the selected node runtime result and error from runStore', async () => {
  useUiStore().selectedNodeIds = ['a']
  const wrapper = shallowMount(PropertiesPanel)
  expect(wrapper.find('[aria-label="步骤执行结果"]').text()).toContain('尚未执行')
  useRunStore().setNodeState('a', { state: 'failed', error: '未识别到目标', cycle: 2 })
  await flushPromises()
  expect(wrapper.find('.execution-summary').text()).toContain('执行失败')
  expect(wrapper.find('.execution-summary').text()).toContain('未识别到目标')
  expect(wrapper.find('.execution-summary').text()).toContain('第 2 轮')
  useRunStore().setNodeState('a', { state: 'done', message: '已点击目标' })
  await flushPromises()
  expect(wrapper.find('.execution-summary').text()).toContain('执行成功')
  expect(wrapper.find('.execution-summary').text()).not.toContain('未识别到目标')
  wrapper.unmount()
})
