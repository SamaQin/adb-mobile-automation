import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import StepNode from './StepNode.vue'
import { useRunStore } from '../../stores/runStore.js'
import { useUiStore } from '../../stores/uiStore.js'

const workflow = vi.hoisted(() => ({ startWorkflow: vi.fn() }))
vi.mock('../../composables/useWorkflowRun.js', () => ({
  useWorkflowRun: () => ({ startWorkflow: workflow.startWorkflow }),
}))
vi.mock('@vue-flow/core', () => ({
  Handle: { template: '<span />' },
  Position: { Top: 'top', Bottom: 'bottom', Right: 'right' },
}))

function stepData(overrides = {}) {
  const step = {
    id: 's1',
    name: 'Step',
    kind: 'wait',
    enabled: true,
    depends_on: [],
    params: { seconds: 1 },
    ...overrides.step,
  }
  return {
    step,
    def: { label: 'Wait' },
    state: 'idle',
    order: 1,
    outgoingDependencyCount: 0,
    returnTargetName: '',
    ...overrides.data,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  workflow.startWorkflow.mockReset()
  workflow.startWorkflow.mockResolvedValue()
})

it('starts the workflow at the step from the hover action', async () => {
  const wrapper = mount(StepNode, {
    props: { id: 's1', data: stepData(), selected: false },
  })

  const button = wrapper.find('[title="从此步骤运行"]')
  expect(button.exists()).toBe(true)
  await button.trigger('click')
  await flushPromises()

  expect(workflow.startWorkflow).toHaveBeenCalledWith('s1')
  wrapper.unmount()
})

it('disables the start action for a disabled step', () => {
  const wrapper = mount(StepNode, {
    props: { id: 's1', data: stepData({ step: { enabled: false } }), selected: false },
  })

  expect(wrapper.find('[title="从此步骤运行"]').attributes('disabled')).toBeDefined()
  wrapper.unmount()
})

it('hides node actions while a run is preparing or active', async () => {
  const run = useRunStore()
  const wrapper = mount(StepNode, {
    props: { id: 's1', data: stepData(), selected: false },
  })
  run.preparing = true
  await wrapper.vm.$nextTick()
  expect(wrapper.find('[title="从此步骤运行"]').exists()).toBe(false)

  run.preparing = false
  run.state = 'running'
  await wrapper.vm.$nextTick()
  expect(wrapper.find('[title="从此步骤运行"]').exists()).toBe(false)
  wrapper.unmount()
})

it('summarizes recorded actions on the node', () => {
  const wrapper = mount(StepNode, {
    props: {
      id: 's1',
      data: stepData({
        step: {
          kind: 'recorded_actions',
          params: { actions: [
            { type: 'tap', x: 1, y: 2, at: 0 },
            { type: 'swipe', x1: 1, y1: 2, x2: 3, y2: 4, duration: 300, at: 1000 },
          ] },
        },
      }),
      selected: false,
    },
  })

  expect(wrapper.text()).toContain('2 个操作 · 1.3 秒')
  wrapper.unmount()
})

it('reports start failures without letting the click bubble', async () => {
  const ui = useUiStore()
  const notify = vi.spyOn(ui, 'notify').mockImplementation(() => {})
  workflow.startWorkflow.mockRejectedValue(new Error('no device'))
  const wrapper = mount(StepNode, {
    props: { id: 's1', data: stepData(), selected: false },
  })

  await wrapper.find('[title="从此步骤运行"]').trigger('click')
  await flushPromises()

  expect(notify).toHaveBeenCalledWith('no device', 'error')
  wrapper.unmount()
})
