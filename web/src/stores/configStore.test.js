import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useConfigStore } from './configStore.js'
import { useHistoryStore } from './historyStore.js'
import { useLayoutStore } from './layoutStore.js'
import { saveConfig, setAcceleration, fetchConfig, fetchStepDefinitions } from '../api/config.js'
import { normalizeDependencies } from '../flow/createFlow.js'

vi.mock('../flow/createFlow.js', async (original) => {
  const actual = await original()
  return { ...actual, normalizeDependencies: vi.fn(actual.normalizeDependencies) }
})

vi.mock('../api/config.js', () => ({ saveConfig: vi.fn(), fetchConfig: vi.fn(), fetchStepDefinitions: vi.fn(), duplicatePreset: vi.fn(), fetchPresetReferences: vi.fn(), setAcceleration: vi.fn() }))

function setup() {
  const store = useConfigStore()
  store.config = { selected_preset_id: 'p', presets: [{ id: 'p', name: 'test', loop_count: 1, steps: ['a', 'b'].map((id) => ({ id, name: id, kind: 'wait', enabled: true, depends_on: [], params: { seconds: 1 } })) }] }
  store.savedConfig = JSON.stringify(store.config)
  return store
}

beforeEach(() => { setActivePinia(createPinia()); localStorage.clear(); vi.clearAllMocks() })

function branchedSetup() {
  const store = setup()
  const step = (id, depends_on = [], params = {}) => ({ id, name: id, kind: 'wait', enabled: true, depends_on, params })
  store.selectedPreset.steps = [
    step('a'),
    step('parent', [], { branches: { 0: [step('x'), step('y', ['x'], { return_to: 'x' }), step('z', [], { return_to: 'a' })] } }),
    step('b', ['a'], { return_to: 'a' }),
  ]
  store.savedConfig = JSON.stringify(store.config)
  return store
}

const branchId = (id) => `branch:parent:0:${id}`

describe('step mutation scope and bulk operations', () => {
  it.each([
    ['name', (step) => { step.name = 'renamed' }],
    ['parameter', (step) => { step.params.seconds = 2 }],
    ['enabled', (step) => { step.enabled = false }],
  ])('keeps references and skips normalization for %s edits', (_, mutate) => {
    const store = branchedSetup()
    const original = store.selectedPreset.steps[1]
    const branches = original.params.branches
    const dependencies = original.depends_on
    const otherParams = store.selectedPreset.steps[2].params
    store.mutateStep('parent', mutate)
    expect(store.selectedPreset.steps[1]).toBe(original)
    expect(original.params.branches).toBe(branches)
    expect(original.depends_on).toBe(dependencies)
    expect(store.selectedPreset.steps[2].params).toBe(otherParams)
    expect(normalizeDependencies).not.toHaveBeenCalled()
    expect(useHistoryStore().undoStack).toHaveLength(1)
  })

  it.each([
    ['dependencies', (step) => { step.depends_on = ['x', 'missing'] }],
    ['return', (step) => { step.params.return_to = 'missing' }],
    ['branches', (step) => { step.params.branches = { 0: [{ id: 'nested', depends_on: ['missing'], params: {} }] } }],
  ])('normalizes once for %s changes', (_, mutate) => {
    const store = branchedSetup()
    store.mutateStep(branchId('y'), mutate)
    expect(normalizeDependencies).toHaveBeenCalledTimes(1)
    const edited = store.findStep(branchId('y')).step
    expect(edited.depends_on).not.toContain('missing')
    expect(edited.params.return_to).not.toBe('missing')
  })

  it.each([
    ['branch only', [branchId('y'), branchId('x')], 2],
    ['mixed main and branch', ['a', 'b', branchId('x'), branchId('y'), branchId('z')], 5],
    ['selected parent and child', ['a', 'parent', branchId('x'), branchId('y')], 2],
  ])('copies %s in one transaction with one complete ID map', (_, selection, expectedCopies) => {
    const store = branchedSetup()
    const before = store.snapshot()
    const result = store.duplicateSteps([...selection, ...selection])
    expect(result).toHaveLength(expectedCopies)
    expect(normalizeDependencies).toHaveBeenCalledTimes(1)
    expect(useHistoryStore().undoStack).toHaveLength(1)
    const copies = result.map((id) => store.findStep(id).step)
    const byName = new Map(copies.map((step) => [step.name, step]))
    const x = byName.get('x 副本')
    const y = byName.get('y 副本')
    if (x && y) {
      expect(y.depends_on).toEqual([x.id])
      expect(y.params.return_to).toBe(x.id)
    }
    const a = byName.get('a 副本')
    const b = byName.get('b 副本')
    if (a && b) {
      expect(b.depends_on).toEqual([a.id])
      expect(b.params.return_to).toBe(a.id)
      expect(byName.get('z 副本').params.return_to).toBe(a.id)
    }
    const parent = byName.get('parent 副本')
    if (parent) {
      const children = parent.params.branches[0]
      expect(children).toHaveLength(3)
      expect(children[1].depends_on).toEqual([children[0].id])
      expect(children[1].params.return_to).toBe(children[0].id)
      expect(children[2].params.return_to).toBe(a.id)
    }
    store.replaceFromHistory(useHistoryStore().undo(store.snapshot()))
    expect(store.snapshot()).toEqual(before)
  })

  it('deletes selected main and branch steps once and clears removed references', () => {
    const store = branchedSetup()
    store.deleteSteps(['a', branchId('x'), branchId('x'), 'missing'])
    expect(normalizeDependencies).toHaveBeenCalledTimes(1)
    expect(useHistoryStore().undoStack).toHaveLength(1)
    expect(store.selectedPreset.steps.map((step) => step.id)).toEqual(['parent', 'b'])
    expect(store.findStep(branchId('y')).step.depends_on).toEqual([])
    expect(store.findStep(branchId('y')).step.params.return_to).toBeUndefined()
    expect(store.findStep(branchId('z')).step.params.return_to).toBeUndefined()
    expect(store.findStep('b').step.depends_on).toEqual([])
    expect(store.findStep('b').step.params.return_to).toBeUndefined()
  })

  it('skips empty, unknown, and unchanged bulk operations', () => {
    const store = setup()
    store.deleteSteps(['missing'])
    expect(store.duplicateSteps(['missing'])).toEqual([])
    store.reorderSteps(['a', 'b'])
    store.reorderSteps(['a', 'a'])
    expect(useHistoryStore().undoStack).toHaveLength(0)
    expect(normalizeDependencies).not.toHaveBeenCalled()
    expect(store.dirty).toBe(false)
  })
})

describe('editing and persistence', () => {
  it('records a batch once and restores it in one undo', () => {
    const store = setup()
    store.setStepsEnabled(['a', 'b'], false)
    expect(useHistoryStore().undoStack).toHaveLength(1)
    store.replaceFromHistory(useHistoryStore().undo(store.snapshot()))
    expect(store.selectedPreset.steps.every((s) => s.enabled)).toBe(true)
    expect(store.dirty).toBe(false)
  })

  it('does not add history or mark dirty for unchanged fields', () => {
    const store = setup()
    store.mutateStep('a', (s) => { s.name = 'a' })
    store.setStepsEnabled(['a', 'b'], true)
    expect(useHistoryStore().undoStack).toHaveLength(0)
    expect(store.dirty).toBe(false)
  })

  it('does not replace edits made while reconnect configuration is loading', async () => {
    const store = setup()
    const remote = JSON.parse(JSON.stringify(store.config))
    let resolve
    fetchConfig.mockImplementation(() => new Promise((done) => { resolve = done }))
    fetchStepDefinitions.mockResolvedValue([])
    const loading = store.load()
    store.mutateStep('a', (s) => { s.name = 'local edit' })
    resolve(remote)
    await loading
    expect(store.selectedPreset.steps[0].name).toBe('local edit')
    expect(store.dirty).toBe(true)
    expect(useHistoryStore().canUndo).toBe(true)
  })

  it('coalesces saves and preserves newer edits and history after a delayed response', async () => {
    const store = setup()
    let resolve
    saveConfig.mockImplementation(() => new Promise((done) => { resolve = done }))
    store.mutateStep('a', (s) => { s.name = 'sent' })
    const saving = store.save()
    const duplicate = store.save()
    await Promise.resolve()
    const sent = JSON.parse(JSON.stringify(store.config))
    store.mutateStep('a', (s) => { s.name = 'newer' })
    resolve(sent)
    await Promise.all([saving, duplicate])
    expect(saveConfig).toHaveBeenCalledTimes(1)
    expect(store.selectedPreset.steps[0].name).toBe('newer')
    expect(store.dirty).toBe(true)
    expect(useHistoryStore().canUndo).toBe(true)
    expect(store.saving).toBe(false)
  })

  it('preserves undo after a successful save and recomputes dirty against the saved baseline', async () => {
    const store = setup()
    store.mutateStep('a', (s) => { s.name = 'saved' })
    saveConfig.mockImplementation(async (value) => value)
    await store.save()
    expect(store.dirty).toBe(false)
    store.replaceFromHistory(useHistoryStore().undo(store.snapshot()))
    expect(store.selectedPreset.steps[0].name).toBe('a')
    expect(store.dirty).toBe(true)
    store.replaceFromHistory(useHistoryStore().redo(store.snapshot()))
    expect(store.dirty).toBe(false)
  })

  it('tracks the persisted acceleration baseline when undoing a setting change', async () => {
    const store = setup()
    store.config.acceleration = 'cpu'
    store.savedConfig = JSON.stringify(store.config)
    setAcceleration.mockResolvedValue({ acceleration: 'gpu' })
    await store.setAcceleration('gpu')
    expect(store.dirty).toBe(false)
    store.replaceFromHistory(useHistoryStore().undo(store.snapshot()))
    expect(store.config.acceleration).toBe('cpu')
    expect(store.dirty).toBe(true)
  })

  it('preserves layouts loaded after an older configuration snapshot', () => {
    const store = setup()
    const layout = useLayoutStore()
    layout.setLayout('p', { a: { x: 0, y: 0 } })
    store.mutateStep('a', (s) => { s.name = 'changed' })
    layout.setLayout('other', { custom: { x: 900, y: 700 } })
    store.replaceFromHistory(useHistoryStore().undo(store.snapshot()))
    expect(layout.get('other').custom).toEqual({ x: 900, y: 700 })
    expect(JSON.parse(localStorage.getItem('layout:other')).custom).toEqual({ x: 900, y: 700 })
  })

  it('saves all dragged coordinates once and supports layout undo and redo', () => {
    const store = setup()
    const layout = useLayoutStore()
    layout.setLayout('p', { a: { x: 0, y: 0 }, b: { x: 100, y: 100 } })
    const revision = layout.revision
    const persist = vi.spyOn(localStorage, 'setItem')
    layout.setPositions('p', [{ id: 'a', position: { x: 30, y: 40 } }, { id: 'b', position: { x: 130, y: 140 } }])
    expect(layout.revision).toBe(revision + 1)
    expect(persist).toHaveBeenCalledTimes(1)
    expect(useHistoryStore().undoStack).toHaveLength(1)
    expect(JSON.parse(localStorage.getItem('layout:p')).b).toEqual({ x: 130, y: 140 })
    store.replaceFromHistory(useHistoryStore().undo(store.snapshot()))
    expect(layout.get('p').a).toEqual({ x: 0, y: 0 })
    expect(layout.get('p').b).toEqual({ x: 100, y: 100 })
    store.replaceFromHistory(useHistoryStore().redo(store.snapshot()))
    expect(layout.get('p').b).toEqual({ x: 130, y: 140 })
    persist.mockRestore()
  })
})
