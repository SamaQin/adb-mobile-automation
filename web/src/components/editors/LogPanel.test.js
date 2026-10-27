import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useRunStore } from '../../stores/runStore.js'
import { useUiStore } from '../../stores/uiStore.js'
import LogPanel from './LogPanel.vue'

let wrapper, run, ui
const line = (id) => ({ id: String(id), text: `line ${id}`, time: new Date(2026, 0, 1, 12) })
async function settle() { await nextTick(); await nextTick() }
function geometry(element) {
  Object.defineProperties(element, {
    clientHeight: { configurable: true, get: () => 100 },
    scrollHeight: { configurable: true, get: () => element.children.length * 22 },
  })
}
function rowGeometry(element) {
  for (const child of element.children) {
    const initial = Number(child.dataset.logId)
    Object.defineProperties(child, {
      offsetTop: { configurable: true, get: () => (initial - Number(element.firstElementChild.dataset.logId)) * 22 },
      offsetHeight: { configurable: true, get: () => 22 },
    })
  }
}
beforeEach(() => {
  setActivePinia(createPinia())
  run = useRunStore()
  ui = useUiStore()
})
afterEach(() => { wrapper?.unmount(); vi.restoreAllMocks() })

describe('bounded runtime log following', () => {
  it('follows new ids when length stays at 500 and stops following when the user scrolls up', async () => {
    run.logs = Array.from({ length: 500 }, (_, id) => line(id))
    wrapper = mount(LogPanel)
    await settle()
    const element = wrapper.get('.log-scroll').element
    geometry(element)
    rowGeometry(element)
    element.scrollTop = 10900
    await wrapper.get('.log-scroll').trigger('scroll')
    run.logs.push(line(500))
    run.logs.shift()
    await settle()
    expect(run.logs).toHaveLength(500)
    expect(element.scrollTop).toBe(11000)

    element.scrollTop = 220
    await wrapper.get('.log-scroll').trigger('scroll')
    const anchor = element.children[10].dataset.logId
    run.logs.push(line(501))
    run.logs.shift()
    await settle()
    expect(element.children[9].dataset.logId).toBe(anchor)
    expect(element.scrollTop).toBe(198)
  })

  it('formats only new rows and does no row or scroll work while collapsed', async () => {
    const format = vi.spyOn(Date.prototype, 'toLocaleTimeString')
    run.logs = [line(1), line(2)]
    wrapper = mount(LogPanel)
    await settle()
    expect(format).toHaveBeenCalledTimes(2)
    run.logs.push(line(3))
    await settle()
    expect(format).toHaveBeenCalledTimes(3)
    ui.logCollapsed = true
    await settle()
    const count = format.mock.calls.length
    run.logs.push(line(4), line(5))
    await settle()
    expect(format).toHaveBeenCalledTimes(count)
    expect(wrapper.find('.log-scroll').exists()).toBe(false)
    ui.logCollapsed = false
    await settle()
    expect(wrapper.findAll('.log-line')).toHaveLength(5)
    expect(format).toHaveBeenCalledTimes(count + 5)
  })

  it('restores the historical anchor after collapse and handles clear through the store', async () => {
    run.logs = Array.from({ length: 20 }, (_, id) => line(id))
    wrapper = mount(LogPanel)
    await settle()
    const element = wrapper.get('.log-scroll').element
    geometry(element)
    rowGeometry(element)
    element.scrollTop = 110
    await wrapper.get('.log-scroll').trigger('scroll')
    ui.logCollapsed = true
    await settle()
    run.logs.shift()
    run.logs.push(line(20))
    ui.logCollapsed = false
    await nextTick()
    const reopened = wrapper.get('.log-scroll').element
    geometry(reopened)
    rowGeometry(reopened)
    await settle()
    expect(reopened.scrollTop).toBe(88)
    const clear = vi.spyOn(run, 'clearLogs')
    await wrapper.get('[title="清空日志"]').trigger('click')
    expect(clear).toHaveBeenCalledOnce()
    expect(wrapper.findAll('.log-line')).toHaveLength(0)
  })

  it('does not render rows when the document is hidden and preserves node focus', async () => {
    run.logs = [{ ...line(1), step_id: 'node' }]
    wrapper = mount(LogPanel)
    await settle()
    await wrapper.get('.log-line').trigger('click')
    expect(wrapper.emitted('focus-node')).toEqual([['node']])
    const format = vi.spyOn(Date.prototype, 'toLocaleTimeString')
    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    document.dispatchEvent(new Event('visibilitychange'))
    await settle()
    run.logs.push(line(2))
    await settle()
    expect(format).not.toHaveBeenCalled()
    expect(wrapper.find('.log-scroll').exists()).toBe(false)
    visibility.mockReturnValue('visible')
    document.dispatchEvent(new Event('visibilitychange'))
    await settle()
    expect(wrapper.findAll('.log-line')).toHaveLength(2)
  })
})
