import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import RecordedActionsField from './RecordedActionsField.vue'
import { useConfigStore } from '../../stores/configStore.js'
import { useDeviceStore } from '../../stores/deviceStore.js'
import { useUiStore } from '../../stores/uiStore.js'

vi.mock('../recording/ActionRecorder.vue', () => ({
  default: {
    props: ['resolution', 'serial', 'stepName'],
    emits: ['complete', 'cancel'],
    template: `
      <div class="recorder-stub">
        <button class="complete" @click="$emit('complete', [{ type: 'tap', x: 1, y: 2, at: 0 }])">complete</button>
        <button class="cancel" @click="$emit('cancel')">cancel</button>
      </div>
    `,
  },
}))

let config, device, ui

beforeEach(() => {
  setActivePinia(createPinia())
  config = useConfigStore()
  config.config = {
    acceleration: 'cpu',
    selected_preset_id: 'p',
    presets: [{
      id: 'p',
      name: 'Preset',
      loop_count: 1,
      steps: [{
        id: 's',
        name: '录制',
        kind: 'recorded_actions',
        enabled: true,
        depends_on: [],
        params: { actions: [] },
        screen_resolution: null,
      }],
    }],
  }
  device = useDeviceStore()
  device.connected = true
  device.resolution = { width: 1000, height: 2000 }
  device.selectedSerial = 'USB123'
  device.devices = [{ serial: 'USB123', state: 'device' }]
  ui = useUiStore()
})

afterEach(() => { document.body.innerHTML = '' })

function mountField(disabled = false) {
  return mount(RecordedActionsField, {
    props: { nodeId: 's', step: config.selectedPreset.steps[0], disabled },
  })
}

async function clickStub(selector) {
  document.querySelector(selector)?.click()
  await flushPromises()
}

it('opens the recorder and writes actions plus resolution back to the step', async () => {
  const wrapper = mountField()
  expect(wrapper.text()).toContain('尚未录制')

  const record = wrapper.findAll('button').find((button) => button.text().includes('录制操作'))
  await record.trigger('click')
  await flushPromises()
  expect(document.querySelector('.recorder-stub')).not.toBeNull()

  await clickStub('.complete')

  const step = config.selectedPreset.steps[0]
  expect(step.params.actions).toEqual([{ type: 'tap', x: 1, y: 2, at: 0 }])
  expect(step.screen_resolution).toEqual({ width: 1000, height: 2000 })
  expect(wrapper.text()).toContain('已录制 1 个操作')
  expect(document.querySelector('.recorder-stub')).toBeNull()
})

it('requires confirmation before replacing or clearing an existing recording', async () => {
  config.selectedPreset.steps[0].params.actions = [{ type: 'tap', x: 4, y: 5, at: 0 }]
  const wrapper = mountField()
  const confirm = vi.spyOn(ui, 'confirmAction').mockResolvedValue(true)

  const reRecord = wrapper.findAll('button').find((button) => button.text().includes('重新录制'))
  await reRecord.trigger('click')
  await flushPromises()
  expect(confirm).toHaveBeenCalledTimes(1)
  expect(document.querySelector('.recorder-stub')).not.toBeNull()
  await clickStub('.cancel')

  const clear = wrapper.findAll('button').find((button) => button.text() === '清除')
  await clear.trigger('click')
  await flushPromises()
  expect(confirm).toHaveBeenCalledTimes(2)
  expect(config.selectedPreset.steps[0].params.actions).toEqual([])
  expect(config.selectedPreset.steps[0].screen_resolution).toBeNull()
})

it('does not open the recorder while disabled', async () => {
  const wrapper = mountField(true)
  const record = wrapper.findAll('button').find((button) => button.text().includes('录制操作'))
  expect(record.attributes('disabled')).toBeDefined()
  await record.trigger('click')
  await flushPromises()
  expect(document.querySelector('.recorder-stub')).toBeNull()
})
