import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it } from 'vitest'
import WorkspaceStatus from './WorkspaceStatus.vue'
import { useConfigStore } from '../stores/configStore.js'
import { useRunStore } from '../stores/runStore.js'

beforeEach(() => setActivePinia(createPinia()))
it('shows save and connection state and locates failed steps', async () => {
  const config = useConfigStore()
  config.config = { selected_preset_id: 'p', presets: [{ id: 'p', name: 'p', steps: [{ id: 'a', name: '识别按钮' }] }] }
  config.dirty = true
  const run = useRunStore()
  run.wsState = 'disconnected'
  run.status = 'failed'
  run.message = '没有可用模板'
  run.nodeStates = { a: { state: 'failed' } }
  const wrapper = mount(WorkspaceStatus)
  expect(wrapper.text()).toContain('有未保存修改')
  expect(wrapper.text()).toContain('正在重连')
  expect(wrapper.text()).toContain('没有可用模板')
  await wrapper.find('.status-locate').trigger('click')
  expect(wrapper.emitted('focus-node')[0]).toEqual(['a'])
  wrapper.unmount()
})
