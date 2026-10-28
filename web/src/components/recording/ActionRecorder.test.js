import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import ActionRecorder from './ActionRecorder.vue'
import { useUiStore } from '../../stores/uiStore.js'

const input = vi.hoisted(() => ({ sendDeviceInput: vi.fn() }))
vi.mock('../../api/device.js', () => ({ sendDeviceInput: input.sendDeviceInput }))
vi.mock('../../composables/useDeviceStream.js', async () => {
  const { ref } = await import('vue')
  const stream = {
    canvas: ref(null), live: ref(true), loading: ref(false), error: ref(''),
    codec: ref('jpeg'), start: vi.fn(), stop: vi.fn(), retry: vi.fn(),
  }
  globalThis.__recordingStream = stream
  return { useDeviceStream: () => stream }
})

beforeEach(() => {
  setActivePinia(createPinia())
  input.sendDeviceInput.mockReset()
  input.sendDeviceInput.mockResolvedValue({ ok: true })
  vi.restoreAllMocks()
})

function mountRecorder() {
  const wrapper = mount(ActionRecorder, {
    attachTo: document.body,
    props: {
      resolution: { width: 1000, height: 2000 },
      serial: 'USB123',
      stepName: '录制步骤',
    },
  })
  const canvas = wrapper.find('canvas').element
  canvas.width = 100
  canvas.height = 200
  canvas.getBoundingClientRect = () => ({
    left: 0, top: 0, width: 200, height: 400, right: 200, bottom: 400, x: 0, y: 0,
    toJSON: () => ({}),
  })
  return wrapper
}

async function gesture(wrapper, start, end, times) {
  const now = vi.spyOn(performance, 'now')
  now.mockReturnValueOnce(times[0])
  now.mockReturnValueOnce(times[1])
  const overlay = wrapper.find('.recording-input-layer')
  await overlay.trigger('pointerdown', {
    clientX: start.x, clientY: start.y, button: 0, pointerId: 1, isPrimary: true,
  })
  if (end) {
    await overlay.trigger('pointermove', {
      clientX: end.x, clientY: end.y, button: 0, pointerId: 1,
    })
  }
  await overlay.trigger('pointerup', {
    clientX: (end || start).x, clientY: (end || start).y, button: 0, pointerId: 1,
  })
  await flushPromises()
}

it('starts on the first gesture and completes with a tap at time zero', async () => {
  const wrapper = mountRecorder()
  expect(useUiStore().recordingOpen).toBe(true)

  await gesture(wrapper, { x: 100, y: 100 }, null, [1000, 1100])

  expect(input.sendDeviceInput).toHaveBeenCalledWith({
    type: 'tap', x: 500, y: 500, serial: 'USB123',
  })
  const finish = wrapper.findAll('button').find((button) => button.text().includes('完成录制'))
  await finish.trigger('click')
  await flushPromises()

  expect(wrapper.emitted('complete')?.[0]?.[0]).toEqual([
    { type: 'tap', x: 500, y: 500, at: 0 },
  ])
  wrapper.unmount()
})

it('records a drag with the relative start time and send payload', async () => {
  const wrapper = mountRecorder()
  await gesture(wrapper, { x: 100, y: 100 }, { x: 200, y: 100 }, [1000, 1250])

  expect(input.sendDeviceInput).toHaveBeenCalledWith({
    type: 'swipe', x1: 500, y1: 500, x2: 999, y2: 500,
    duration: 250, serial: 'USB123',
  })
  const finish = wrapper.findAll('button').find((button) => button.text().includes('完成录制'))
  await finish.trigger('click')
  await flushPromises()
  expect(wrapper.emitted('complete')?.[0]?.[0]).toEqual([
    { type: 'swipe', x1: 500, y1: 500, x2: 999, y2: 500, duration: 250, at: 0 },
  ])
  wrapper.unmount()
})

it('keeps the relative gap between the first and later actions', async () => {
  const wrapper = mountRecorder()
  await gesture(wrapper, { x: 100, y: 100 }, null, [1000, 1100])
  await gesture(wrapper, { x: 100, y: 100 }, null, [2500, 2600])

  const finish = wrapper.findAll('button').find((button) => button.text().includes('完成录制'))
  await finish.trigger('click')
  await flushPromises()

  expect(wrapper.emitted('complete')?.[0]?.[0]).toEqual([
    { type: 'tap', x: 500, y: 500, at: 0 },
    { type: 'tap', x: 500, y: 500, at: 1500 },
  ])
  expect(input.sendDeviceInput).toHaveBeenCalledTimes(2)
  wrapper.unmount()
})

it('does not complete without an action and ignores pre-first-input wait', async () => {
  const wrapper = mountRecorder()
  const finish = wrapper.findAll('button').find((button) => button.text().includes('完成录制'))
  expect(finish.attributes('disabled')).toBeDefined()

  await gesture(wrapper, { x: 100, y: 100 }, null, [5000, 5200])
  await finish.trigger('click')
  await flushPromises()
  expect(wrapper.emitted('complete')?.[0]?.[0]?.[0]?.at).toBe(0)
  wrapper.unmount()
})

it('stops accepting gestures after a resolution change', async () => {
  const wrapper = mountRecorder()
  await gesture(wrapper, { x: 100, y: 100 }, null, [1000, 1100])
  await wrapper.setProps({ resolution: { width: 2000, height: 4000 } })
  await wrapper.vm.$nextTick()

  expect(wrapper.find('.recording-error').text()).toContain('分辨率')
  const overlay = wrapper.find('.recording-input-layer')
  await overlay.trigger('pointerdown', {
    clientX: 100, clientY: 100, button: 0, pointerId: 2, isPrimary: true,
  })
  expect(wrapper.findAll('.recording-action')).toHaveLength(1)
  wrapper.unmount()
})

it('cancels with confirmation and clears the global recording flag', async () => {
  const wrapper = mountRecorder()
  const ui = useUiStore()
  const confirm = vi.spyOn(ui, 'confirmAction').mockResolvedValue(true)
  await gesture(wrapper, { x: 100, y: 100 }, null, [1000, 1100])

  const cancel = wrapper.findAll('button').find((button) => button.text() === '取消')
  await cancel.trigger('click')
  await flushPromises()

  expect(confirm).toHaveBeenCalledTimes(1)
  expect(wrapper.emitted('cancel')).toBeTruthy()
  wrapper.unmount()
  expect(ui.recordingOpen).toBe(false)
})
