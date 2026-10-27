import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { useTemplateStore } from '../../stores/templateStore.js'
import TemplateManager from './TemplateManager.vue'

vi.mock('../../api/templates.js', () => ({ fetchTemplates: vi.fn(async () => Array.from({ length: 145 }, (_, i) => ({ name: `template-${String(i).padStart(3, '0')}.png`, revision: '1', width: 10, height: 10 }))), templateThumbnailUrl: (name) => `/thumb/${name}` }))
beforeEach(() => setActivePinia(createPinia()))

it('bounds template cards per page and resets pagination when searching', async () => {
  const wrapper = mount(TemplateManager)
  await flushPromises()
  expect(useTemplateStore().items).toHaveLength(145)
  expect(wrapper.findAll('.template-item')).toHaveLength(60)
  const next = wrapper.findAll('.template-pagination button')[1]
  await next.trigger('click')
  expect(wrapper.find('.template-item strong').text()).toBe('template-060.png')
  await wrapper.find('input[type="search"]').setValue('template-144')
  expect(wrapper.findAll('.template-item')).toHaveLength(1)
  expect(wrapper.find('.template-item strong').text()).toBe('template-144.png')
  expect(wrapper.find('.template-pagination').exists()).toBe(false)
  wrapper.unmount()
})
