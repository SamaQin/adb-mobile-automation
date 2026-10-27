import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useConfigStore } from './configStore.js'
import { useHistoryStore } from './historyStore.js'
import { useLayoutStore } from './layoutStore.js'

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  vi.restoreAllMocks()
  useConfigStore().config = { selected_preset_id: 'p', presets: [{ id: 'p', steps: [] }] }
})

describe('layout persistence', () => {
  it.each(['positions', 'layout', 'reset'])('does not record or persist repeated %s gestures', (operation) => {
    const store = useLayoutStore()
    store.setLayout('p', { a: { x: 0, y: 0 } })
    const persist = vi.spyOn(localStorage, 'setItem')
    const apply = () => {
      if (operation === 'positions') store.setPositions('p', [{ id: 'a', position: { x: 30, y: 40 } }])
      if (operation === 'layout') store.setLayout('p', { a: { x: 30, y: 40 } }, true)
      if (operation === 'reset') store.reset('p')
    }
    apply()
    apply()
    expect(useHistoryStore().undoStack).toHaveLength(1)
    expect(persist).toHaveBeenCalledTimes(1)
  })

  it('resets to automatic positions with one history entry and one browser write', () => {
    const store = useLayoutStore()
    store.setLayout('p', { a: { x: 1, y: 2 }, __groups: { group: { id: 'group' } } })
    const persist = vi.spyOn(localStorage, 'setItem')
    store.reset('p', true)
    store.reset('p', true)
    expect(persist).toHaveBeenCalledTimes(1)
    expect(useHistoryStore().undoStack).toHaveLength(1)
    expect(store.get('p').start).toBeDefined()
    expect(store.get('p').__groups).toEqual({})
  })

  it('skips identical single positions and restores without redundant writes', () => {
    const store = useLayoutStore()
    store.setPosition('p', 'a', { x: 1, y: 2 })
    const persist = vi.spyOn(localStorage, 'setItem')
    const revision = store.revision
    store.setPosition('p', 'a', { x: 1, y: 2 })
    store.setPosition('p', 'a', { x: NaN, y: 2 })
    store.restore({ p: store.get('p') })
    store.persist('p')
    expect(persist).not.toHaveBeenCalled()
    expect(store.revision).toBe(revision)
  })

  it('restores multiple loaded layouts together through undo and redo', () => {
    const config = useConfigStore()
    const store = useLayoutStore()
    store.setLayout('p', { a: { x: 1, y: 2 } })
    store.setLayout('q', { b: { x: 3, y: 4 } })
    store.setPositions('p', [{ id: 'a', position: { x: 10, y: 20 } }])
    store.setPositions('q', [{ id: 'b', position: { x: 30, y: 40 } }])
    config.replaceFromHistory(useHistoryStore().undo(config.snapshot()))
    expect(store.get('p').a).toEqual({ x: 10, y: 20 })
    expect(store.get('q').b).toEqual({ x: 3, y: 4 })
    config.replaceFromHistory(useHistoryStore().undo(config.snapshot()))
    expect(store.get('p').a).toEqual({ x: 1, y: 2 })
    config.replaceFromHistory(useHistoryStore().redo(config.snapshot()))
    expect(store.get('p').a).toEqual({ x: 10, y: 20 })
    config.replaceFromHistory(useHistoryStore().redo(config.snapshot()))
    expect(store.get('q').b).toEqual({ x: 30, y: 40 })
  })
})
