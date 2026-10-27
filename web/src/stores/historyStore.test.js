import { beforeEach, describe, expect, it, vi } from 'vitest'
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

  it('retains only serialized data and serializes each incoming state once', () => {
    const store = useHistoryStore()
    const stringify = vi.spyOn(JSON, 'stringify')
    store.push({ nested: { value: 1 } })
    store.push({ nested: { value: 1 } })
    expect(stringify).toHaveBeenCalledTimes(2)
    expect(store.undoStack).toHaveLength(1)
    const entry = store.undoStack[0]
    expect(Object.getOwnPropertyDescriptor(entry, 'snapshot').get).toBeTypeOf('function')
    const snapshot = entry.snapshot
    snapshot.nested.value = 9
    expect(entry.snapshot.nested.value).toBe(1)
    expect(entry.bytes).toBe(entry.serialized.length * 2)
    stringify.mockRestore()
  })

  it.each([
    { limit: 3, byteLimit: 10000, sizes: [10, 20, 30, 40], expected: [1, 2, 3] },
    { limit: 50, byteLimit: 180, sizes: [10, 10, 10, 10], expected: [2, 3] },
    { limit: 50, byteLimit: 80, sizes: [10, 200], expected: [1] },
  ])('bounds retained states for $sizes with $byteLimit bytes', ({ limit, byteLimit, sizes, expected }) => {
    const store = useHistoryStore()
    store.limit = limit
    store.byteLimit = byteLimit
    sizes.forEach((size, index) => store.push({ index, data: '中'.repeat(size) }))
    expect(store.undoStack.map((entry) => entry.snapshot.index)).toEqual(expected)
    expect(store.retainedBytes <= byteLimit || store.undoStack.length === 1).toBe(true)
  })

  it('applies one shared budget during undo and redo, preserving the nearest oversized state', () => {
    const store = useHistoryStore()
    store.byteLimit = 200
    store.push({ value: 1 })
    store.push({ value: 2 })
    const huge = { data: 'x'.repeat(1000) }
    expect(store.undo(huge)).toEqual({ value: 2 })
    expect(store.undoStack).toHaveLength(0)
    expect(store.redoStack).toHaveLength(1)
    expect(store.redo({ value: 2 })).toEqual(huge)
    expect(store.retainedBytes).toBeLessThanOrEqual(store.byteLimit)
    store.clear()
    expect(store.retainedBytes).toBe(0)
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
