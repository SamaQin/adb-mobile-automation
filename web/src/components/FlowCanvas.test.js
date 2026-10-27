import { shallowMount } from '@vue/test-utils'
import { nextTick, reactive } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useConfigStore } from '../stores/configStore.js'
import { useLayoutStore } from '../stores/layoutStore.js'
import { useRunStore } from '../stores/runStore.js'
import { useUiStore } from '../stores/uiStore.js'
import { createFlow } from '../flow/createFlow.js'
import FlowCanvas from './FlowCanvas.vue'

const flowApi = vi.hoisted(() => ({ updateNodeInternals: vi.fn(), fitView: vi.fn() }))
vi.mock('@vue-flow/core', () => ({
  VueFlow: { name: 'VueFlow', props: ['nodes', 'edges', 'isValidConnection', 'elementsSelectable', 'nodesDraggable', 'nodesConnectable'], template: '<div />' },
  Handle: { template: '<span />' }, Position: { Top: 'top', Bottom: 'bottom', Right: 'right' },
  useVueFlow: () => ({ ...flowApi, zoomIn: vi.fn(), zoomOut: vi.fn(), screenToFlowCoordinate: (p) => p, setCenter: vi.fn(), getViewport: () => ({ zoom: 1 }) }),
}))
vi.mock('../flow/createFlow.js', async (original) => {
  const module = await original()
  return { ...module, createFlow: vi.fn(module.createFlow) }
})

const step = (id, params = {}) => ({ id, name: id, kind: 'wait', enabled: true, depends_on: [], params: { seconds: 1, ...params } })
let config, layout, wrapper
async function setup() {
  config.config = { presets: [{ id: 'p', name: 'Preset', steps: [step('a'), step('b', { return_to: 'a' })] }] }
  config.config.selected_preset_id = 'p'
  wrapper = shallowMount(FlowCanvas)
  await nextTick()
  return wrapper
}
beforeEach(() => {
  const storage = new Map()
  vi.stubGlobal('localStorage', { getItem: (key) => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: (key) => storage.delete(key) })
  setActivePinia(createPinia())
  config = useConfigStore()
  layout = useLayoutStore()
  vi.clearAllMocks()
})

describe('FlowCanvas incremental updates', () => {
  it('updates only dirty nodes and their edges while preserving same-tick terminal states', async () => {
    await setup()
    config.selectedPreset.steps.push(step('unrelated'))
    await nextTick()
    await nextTick()
    const run = useRunStore()
    run.applyStatus({ state: 'running', node_states: {} })
    await nextTick()
    const unrelated = wrapper.vm.nodes.find((node) => node.id === 'unrelated')
    const read = vi.fn(() => 'idle')
    Object.defineProperty(unrelated.data, 'state', { get: read, set: vi.fn(), configurable: true })
    run.handleEvent({ type: 'step', data: { step_id: 'a', frame_id: 'root', state: 'running' } })
    run.handleEvent({ type: 'step', data: { step_id: 'a', frame_id: 'root', state: 'failed', message: 'boom' } })
    await nextTick()
    expect(read).not.toHaveBeenCalled()
    expect(wrapper.vm.nodes.find((node) => node.id === 'a').data).toMatchObject({ state: 'failed', error: 'boom' })
    expect(wrapper.vm.edges.every((edge) => !edge.animated)).toBe(true)
    wrapper.unmount()
  })

  it('syncs shallow replacements, reset barriers, frame resets and running-only transitions', async () => {
    await setup()
    const run = useRunStore()
    run.nodeStates = { a: { state: 'running', frame_id: 'root' }, b: { state: 'failed', frame_id: 'child', error: 'old' } }
    await nextTick()
    expect(wrapper.vm.nodes.find((node) => node.id === 'a').data.state).toBe('running')
    expect(wrapper.vm.edges.every((edge) => !edge.animated)).toBe(true)
    run.state = 'running'
    await nextTick()
    expect(wrapper.vm.edges.some((edge) => edge.animated)).toBe(true)
    run.applyStatus({ state: 'running', reset_frame_id: 'child' })
    await nextTick()
    expect(wrapper.vm.nodes.find((node) => node.id === 'b').data).toMatchObject({ state: 'idle', error: '' })
    run.applyStatus({ state: 'running', root_cycle: 2 })
    run.handleEvent({ type: 'step', data: { step_id: 'b', state: 'done' } })
    await nextTick()
    expect(wrapper.vm.nodes.find((node) => node.id === 'a').data.state).toBe('idle')
    expect(wrapper.vm.nodes.find((node) => node.id === 'b').data.state).toBe('done')
    run.handleEvent({ type: 'step', data: { step_id: 'a', state: 'running' } })
    run.handleEvent({ type: 'finished', data: { status: 'failed', node_states: { a: { state: 'failed', error: 'final' }, b: { state: 'done' } } } })
    await nextTick()
    expect(wrapper.vm.nodes.find((node) => node.id === 'a').data).toMatchObject({ state: 'failed', error: 'final' })
    expect(wrapper.vm.edges.every((edge) => !edge.animated)).toBe(true)
    wrapper.unmount()
  })

  it('updates registered graph replacements and recovers after journal overflow', async () => {
    await setup()
    const flow = wrapper.findComponent({ name: 'VueFlow' })
    const registeredEdges = wrapper.vm.edges.map((edge) => ({ ...edge }))
    flow.vm.$emit('update:edges', registeredEdges)
    await nextTick()
    const run = useRunStore()
    run.applyStatus({ state: 'running' })
    await nextTick()
    for (let i = 0; i < 600; i++) run.setNodeState(i % 2 ? 'a' : 'b', { state: 'done' })
    run.setNodeState('a', { state: 'running' })
    await nextTick()
    expect(wrapper.vm.nodes.find((node) => node.id === 'a').data.state).toBe('running')
    expect(registeredEdges.some((edge) => edge.animated)).toBe(true)
    expect(wrapper.vm.nodes.find((node) => node.id === 'b').data.state).toBe('done')
    wrapper.unmount()
  })

  it('indexes branch runtime ids without splitting ids containing colons', async () => {
    await setup()
    config.selectedPreset.steps[0].params.branches = { 0: [step('child:one')] }
    await nextTick()
    await nextTick()
    const run = useRunStore()
    run.applyStatus({ state: 'running' })
    run.handleEvent({ type: 'step', data: { step_id: 'child:one', frame_id: 'child', state: 'running' } })
    await nextTick()
    const branch = wrapper.vm.nodes.find((node) => node.type === 'branch')
    expect(branch.data.state).toBe('running')
    expect(wrapper.vm.edges.filter((edge) => edge.target === branch.id).every((edge) => edge.animated)).toBe(true)
    wrapper.unmount()
  })

  it('keeps registered edges valid while saving and rejects new connections when locked', async () => {
    await setup()
    const validate = wrapper.findComponent({ name: 'VueFlow' }).props('isValidConnection')
    const edge = wrapper.vm.edges.find((item) => item.data.kind === 'return')
    expect(validate(edge)).toBe(true)
    const { id, ...connection } = edge
    expect(validate(connection)).toBe(false)
    config.saving = true
    await nextTick()
    expect(validate(edge)).toBe(true)
    expect(validate({ source: 'start', target: 'b', sourceHandle: 'order-source', targetHandle: 'order-target' })).toBe(false)
    wrapper.unmount()
  })
  it('keeps nodes and edges during ordinary edits, reference replacement, and rename', async () => {
    await setup()
    const node = wrapper.vm.nodes.find((item) => item.id === 'a')
    const edges = wrapper.vm.edges
    const count = createFlow.mock.calls.length
    config.selectedPreset.steps[0].params = { seconds: 42 }
    config.selectedPreset.steps[0].enabled = false
    await nextTick()
    expect(createFlow).toHaveBeenCalledTimes(count)
    expect(wrapper.vm.nodes.find((item) => item.id === 'a')).toBe(node)
    expect(node.data.step.params.seconds).toBe(42)
    expect(wrapper.vm.edges).toBe(edges)
    config.selectedPreset.steps[0] = reactive({ ...step('a'), name: 'Renamed' })
    await nextTick()
    expect(node.data.step).toBe(config.selectedPreset.steps[0])
    expect(wrapper.vm.nodes.find((item) => item.id === 'b').data.returnTargetName).toBe('Renamed')
    expect(createFlow).toHaveBeenCalledTimes(count)
    wrapper.unmount()
  })

  it('applies layout without createFlow and reuses existing edges on topology changes', async () => {
    await setup()
    const edge = wrapper.vm.edges[0]
    const count = createFlow.mock.calls.length
    layout.setPosition('p', 'a', { x: 910, y: 340 })
    await nextTick()
    expect(createFlow).toHaveBeenCalledTimes(count)
    expect(wrapper.vm.nodes.find((node) => node.id === 'a').position).toEqual({ x: 910, y: 340 })
    config.selectedPreset.steps.push(step('c'))
    await nextTick()
    expect(wrapper.vm.edges.find((item) => item.id === edge.id)).toBe(edge)
    expect(wrapper.vm.edges.length).toBeGreaterThan(0)
    expect(wrapper.vm.edges.every((item) => wrapper.vm.nodes.some((node) => node.id === item.target))).toBe(true)
    wrapper.unmount()
  })

  it('saves all multi drag positions in one batch and keeps group movement separate', async () => {
    await setup()
    const batch = vi.spyOn(layout, 'setPositions')
    const groupMove = vi.spyOn(layout, 'moveGroup')
    const moved = [{ id: 'a', type: 'step', position: { x: 4, y: 8 } }, { id: 'b', type: 'step', position: { x: 9, y: 12 } }]
    wrapper.findComponent({ name: 'VueFlow' }).vm.$emit('node-drag-stop', { node: moved[0], nodes: moved })
    expect(batch).toHaveBeenCalledExactlyOnceWith('p', moved.map(({ id, position }) => ({ id, position })))
    wrapper.findComponent({ name: 'VueFlow' }).vm.$emit('node-drag-stop', { node: { id: 'group:g', type: 'group', position: { x: 2, y: 3 } } })
    expect(groupMove).toHaveBeenCalledExactlyOnceWith('p', 'group:g', { x: 2, y: 3 })
    expect(batch).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('measures changed branch handles only and does not rebuild for template threshold edits', async () => {
    await setup()
    flowApi.updateNodeInternals.mockClear()
    const count = createFlow.mock.calls.length
    config.selectedPreset.steps[0].params.branches = { 0: [step('child')] }
    config.selectedPreset.steps[0].params.templates = [{ file: 'target.png', threshold: 0.8 }]
    await nextTick()
    await nextTick()
    await nextTick()
    expect(flowApi.updateNodeInternals).toHaveBeenCalledExactlyOnceWith(['a', 'branch:a:0:child'])
    expect(createFlow).toHaveBeenCalledTimes(count + 1)
    config.selectedPreset.steps[0].params.templates[0].threshold = 0.9
    await nextTick()
    expect(createFlow).toHaveBeenCalledTimes(count + 1)
    const child = wrapper.vm.nodes.find((node) => node.id === 'branch:a:0:child')
    config.selectedPreset.steps[0].params.templates[0].file = 'renamed.png'
    await nextTick()
    expect(child.data.branch.label).toBe('renamed.png')
    expect(flowApi.updateNodeInternals).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('restores default coordinates when history restores an empty layout', async () => {
    await setup()
    const original = wrapper.vm.nodes.map(({ id, position }) => ({ id, position: { ...position } }))
    const count = createFlow.mock.calls.length
    layout.setPositions('p', [{ id: 'a', position: { x: 999, y: 888 } }, { id: 'start', position: { x: 700, y: 600 } }])
    await nextTick()
    layout.setLayout('p', {})
    await nextTick()
    expect(wrapper.vm.nodes.map(({ id, position }) => ({ id, position: { ...position } }))).toEqual(original)
    expect(createFlow).toHaveBeenCalledTimes(count)
    wrapper.unmount()
  })

  it('remeasures nodes for replaced definitions without rebuilding topology', async () => {
    await setup()
    await nextTick()
    flowApi.updateNodeInternals.mockClear()
    const count = createFlow.mock.calls.length
    config.definitions = [{ key: 'wait', label: 'Updated wait', fields: [] }]
    await nextTick()
    await nextTick()
    expect(wrapper.vm.nodes.find((node) => node.id === 'a').data.def.label).toBe('Updated wait')
    expect(flowApi.updateNodeInternals).toHaveBeenCalledExactlyOnceWith(['a', 'b'])
    expect(createFlow).toHaveBeenCalledTimes(count)
    wrapper.unmount()
  })

  it('auto layout and reset apply coordinates without duplicate topology work', async () => {
    await setup()
    const count = createFlow.mock.calls.length
    await wrapper.vm.autoLayout()
    await wrapper.vm.resetLayout()
    expect(createFlow).toHaveBeenCalledTimes(count)
    wrapper.unmount()
  })

  it('uses the new preset positions and valid edge endpoints when switching', async () => {
    await setup()
    config.config.presets.push({ id: 'q', name: 'Next', steps: [step('z')] })
    layout.setPosition('q', 'z', { x: 700, y: 600 })
    config.config.selected_preset_id = 'q'
    await nextTick()
    await nextTick()
    expect(wrapper.vm.nodes.map((node) => node.id)).toEqual(['start', 'z'])
    expect(wrapper.vm.nodes[1].position).toEqual({ x: 700, y: 600 })
    expect(wrapper.vm.edges.map(({ source, target }) => [source, target])).toEqual([['start', 'z']])
    wrapper.unmount()
  })
})


describe('FlowCanvas guidance and adding steps', () => {
  it('allows viewing a selected step while running without enabling edits', async () => {
    await setup()
    const ui = useUiStore()
    ui.propertiesCollapsed = true
    useRunStore().state = 'running'
    await nextTick()
    const flow = wrapper.findComponent({ name: 'VueFlow' })
    expect(flow.props('elementsSelectable')).toBe(true)
    expect(flow.props('nodesDraggable')).toBe(false)
    expect(flow.props('nodesConnectable')).toBe(false)
    flow.vm.$emit('node-click', { event: {}, node: wrapper.vm.nodes.find((node) => node.id === 'a') })
    await nextTick()
    expect(ui.selectedNodeId).toBe('a')
    expect(ui.propertiesCollapsed).toBe(false)
    expect(wrapper.find('.canvas-lock').text()).toContain('可选步骤查看')
    wrapper.unmount()
  })

  it('offers three empty-preset actions and opens settings after one addition', async () => {
    await setup()
    config.definitions = ['wait', 'tap', 'find_and_tap'].map((key) => ({ key, label: key, fields: [] }))
    config.selectedPreset.steps = []
    useUiStore().propertiesCollapsed = true
    await nextTick()
    expect(wrapper.find('.canvas-welcome').text()).toContain('添加第一个步骤')
    expect(wrapper.findAll('.quick-steps button')).toHaveLength(3)
    expect(wrapper.find('.canvas-welcome').text()).toContain('拖到画布')
    wrapper.find('.quick-steps button').element.dispatchEvent(new MouseEvent('click', { detail: 1 }))
    await nextTick()
    expect(config.selectedPreset.steps).toHaveLength(1)
    expect(useUiStore().selectedNodeId).toBe(config.selectedPreset.steps[0].id)
    expect(useUiStore().propertiesCollapsed).toBe(false)
    expect(wrapper.find('.canvas-welcome').exists()).toBe(false)
    expect(wrapper.find('[role="status"]').text()).toContain('第 1 步')
    wrapper.unmount()
  })

  it('keeps clicked additions visible on long flows and preserves insertion order', async () => {
    await setup()
    config.selectedPreset.steps = Array.from({ length: 100 }, (_, index) => step(`s${index}`))
    await nextTick()
    vi.spyOn(wrapper.element, 'getBoundingClientRect').mockReturnValue({ left: 200, top: 100, width: 800, height: 600 })
    const ui = useUiStore()
    ui.selectNode('s5')
    const added = wrapper.vm.addStep('wait')
    await nextTick()
    const position = layout.get('p')[added.id]
    expect(position.x).toBeGreaterThanOrEqual(212)
    expect(position.x + 242).toBeLessThanOrEqual(988)
    expect(position.y).toBeGreaterThanOrEqual(164)
    expect(position.y + 140).toBeLessThanOrEqual(688)
    expect(config.selectedPreset.steps.slice(5, 8).map(({ id }) => id)).toEqual(['s5', added.id, 's6'])
    expect(config.selectedPreset.steps[100].id).toBe('s99')
    wrapper.unmount()
  })

  it('clamps a dropped node inside the view instead of placing it beyond its edge', async () => {
    await setup()
    vi.spyOn(wrapper.element, 'getBoundingClientRect').mockReturnValue({ left: 200, top: 100, width: 800, height: 600 })
    await wrapper.trigger('drop', { clientX: 990, clientY: 690, dataTransfer: { getData: () => 'tap' } })
    const added = config.selectedPreset.steps.at(-1)
    expect(layout.get('p')[added.id]).toEqual({ x: 746, y: 548 })
    expect(useUiStore().selectedNodeId).toBe(added.id)
    wrapper.unmount()
  })

  it('collapses the legend and reopens settings when a different node is selected', async () => {
    await setup()
    expect(wrapper.find('.guide-details').exists()).toBe(false)
    await wrapper.find('.guide-toggle').trigger('click')
    for (const label of ['顺序', '依赖', '分支', '返回', '不改变执行顺序', 'Delete']) expect(wrapper.find('.guide-details').text()).toContain(label)
    const ui = useUiStore()
    ui.propertiesCollapsed = true
    ui.selectNode('a')
    await nextTick()
    expect(ui.propertiesCollapsed).toBe(false)
    await wrapper.find('.guide-toggle').trigger('click')
    expect(wrapper.find('.guide-details').exists()).toBe(false)
    wrapper.unmount()
  })

  it('does not add while locked and leaves modal shortcuts to their dialog', async () => {
    await setup()
    config.selectedPreset.steps = []
    config.definitions = [{ key: 'wait', label: '等待', fields: [] }]
    config.saving = true
    await nextTick()
    expect(wrapper.find('.quick-steps button').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.canvas-lock').text()).toContain('正在保存')
    expect(wrapper.vm.addStep('wait')).toBeUndefined()
    config.saving = false
    config.selectedPreset.steps = [step('a')]
    const ui = useUiStore()
    ui.selectNode('a')
    for (const field of ['dialog', 'helpOpen', 'screenshotRequest', 'templateDrawerOpen']) {
      ui[field] = true
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Delete' }))
      expect(config.selectedPreset.steps).toHaveLength(1)
      ui[field] = null
    }
    wrapper.unmount()
  })
})
