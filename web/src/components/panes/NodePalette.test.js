import { shallowMount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { useConfigStore } from '../../stores/configStore.js'
import { useRunStore } from '../../stores/runStore.js'
import { useUiStore } from '../../stores/uiStore.js'
import NodePalette from './NodePalette.vue'

let config
beforeEach(() => {
  setActivePinia(createPinia())
  config = useConfigStore()
  config.config = { selected_preset_id: 'p', presets: [{ id: 'p', name: 'p', steps: [] }] }
  config.definitions = [
    { key: 'wait', label: '等待', fields: [] },
    { key: 'tap', label: '点击坐标', fields: [] },
    { key: 'find_and_tap', label: '识别模板并点击/连击', fields: [] },
  ]
})

describe('step library', () => {
  it('adds once for a click or double-click and accepts native keyboard activation', async () => {
    const wrapper = shallowMount(NodePalette)
    const button = wrapper.find('.palette-item')
    expect(button.element.tagName).toBe('BUTTON')
    button.element.dispatchEvent(new MouseEvent('click', { detail: 1 }))
    button.element.dispatchEvent(new MouseEvent('click', { detail: 2 }))
    button.element.dispatchEvent(new MouseEvent('dblclick', { detail: 2 }))
    expect(wrapper.emitted('add')).toEqual([['wait']])
    // Enter/Space activate native buttons through a click with detail=0.
    button.element.dispatchEvent(new MouseEvent('click', { detail: 0 }))
    expect(wrapper.emitted('add')).toEqual([['wait'], ['wait']])
    expect(button.text()).toContain('等页面加载')
    wrapper.unmount()
  })

  it('finds Chinese aliases and use cases, and clears an empty result', async () => {
    const wrapper = shallowMount(NodePalette)
    const search = wrapper.find('input')
    await search.setValue('  找图  ')
    expect(wrapper.findAll('.palette-item')).toHaveLength(1)
    expect(wrapper.find('.palette-item').text()).toContain('识别模板')
    await search.setValue('暂停 加载')
    expect(wrapper.findAll('.palette-item')).toHaveLength(1)
    expect(wrapper.find('.palette-item').text()).toContain('等待')
    await search.setValue('不存在的类型')
    expect(wrapper.findAll('.palette-item')).toHaveLength(0)
    expect(wrapper.find('.palette-empty').text()).toContain('没有找到')
    await wrapper.find('.palette-empty button').trigger('click')
    expect(wrapper.findAll('.palette-item')).toHaveLength(3)
    wrapper.unmount()
  })

  it('preserves drag data and explains all disabled states', async () => {
    const wrapper = shallowMount(NodePalette)
    const data = new Map()
    const transfer = { setData: (key, value) => data.set(key, value) }
    await wrapper.find('.palette-item').trigger('dragstart', { dataTransfer: transfer })
    expect(data.get('application/x-step-kind')).toBe('wait')
    for (const [apply, reason] of [
      [() => { config.saving = true }, '正在保存'],
      [() => { config.saving = false; useUiStore().readOnly = true }, '只读模式'],
      [() => { useRunStore().state = 'running' }, '正在运行'],
    ]) {
      apply()
      await wrapper.vm.$nextTick()
      const button = wrapper.find('.palette-item')
      expect(button.attributes('disabled')).toBeDefined()
      expect(button.attributes('title')).toContain(reason)
      await button.trigger('dblclick')
      await button.trigger('click')
    }
    expect(wrapper.emitted('add')).toBeUndefined()
    wrapper.unmount()
  })
})
