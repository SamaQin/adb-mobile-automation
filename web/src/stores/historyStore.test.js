import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useHistoryStore } from './historyStore.js'

describe('history store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('undoes and redoes immutable snapshots', () => {
    const store = useHistoryStore()
    const first = { value: 1, nested: { enabled: true } }
    const second = { value: 2, nested: { enabled: false } }
    store.push(first, 'first')

    const restored = store.undo(second)
    expect(restored).toEqual(first)
    restored.nested.enabled = false
    expect(store.redoStack[0].snapshot).toEqual(second)

    expect(store.redo(first)).toEqual(second)
    expect(store.canUndo).toBe(true)
  })

  it('caps history and removes redo entries after a new edit', () => {
    const store = useHistoryStore()
    store.limit = 2
    store.push({ value: 1 })
    store.push({ value: 2 })
    store.push({ value: 3 })
    expect(store.undoStack.map((entry) => entry.snapshot.value)).toEqual([2, 3])
    store.undo({ value: 4 })
    expect(store.canRedo).toBe(true)
    store.push({ value: 5 })
    expect(store.canRedo).toBe(false)
  })
})
