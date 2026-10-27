import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it } from 'vitest'
import AppDialog from './AppDialog.vue'
import { useUiStore } from '../stores/uiStore.js'

beforeEach(() => setActivePinia(createPinia()))

it('focuses the prompt, submits trimmed text, and restores focus', async () => {
  const trigger = document.createElement('button')
  document.body.appendChild(trigger)
  trigger.focus()
  const ui = useUiStore()
  const wrapper = mount(AppDialog, { attachTo: document.body })
  const result = ui.promptText({ title: '新建预设', initialValue: '初稿' })
  await flushPromises()
  expect(document.activeElement).toBe(wrapper.find('input').element)
  await wrapper.find('input').setValue('  新流程  ')
  await wrapper.find('form').trigger('submit')
  expect(await result).toBe('新流程')
  await flushPromises()
  expect(document.activeElement).toBe(trigger)
  wrapper.unmount(); trigger.remove()
})

it('cancels with Escape and prevents empty prompt submission', async () => {
  const ui = useUiStore()
  const wrapper = mount(AppDialog)
  const result = ui.promptText({ title: '命名' })
  await flushPromises()
  expect(wrapper.find('[type="submit"]').attributes('disabled')).toBeDefined()
  await wrapper.find('form').trigger('submit')
  expect(ui.dialog).not.toBe(null)
  await wrapper.find('.app-dialog-backdrop').trigger('keydown', { key: 'Escape' })
  expect(await result).toBe(null)
  expect(ui.dialog).toBe(null)
  wrapper.unmount()
})

it('resolves destructive confirmations only on explicit submit', async () => {
  const ui = useUiStore()
  const wrapper = mount(AppDialog)
  const cancel = ui.confirmAction({ title: '删除模板？', danger: true })
  await flushPromises()
  await wrapper.find('[data-cancel]').trigger('click')
  expect(await cancel).toBe(false)
  const confirm = ui.confirmAction({ title: '删除模板？', confirmLabel: '删除模板', danger: true })
  await flushPromises()
  expect(wrapper.find('[type="submit"]').classes()).toContain('danger')
  await wrapper.find('form').trigger('submit')
  expect(await confirm).toBe(true)
  wrapper.unmount()
})
