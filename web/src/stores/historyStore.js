import { defineStore } from 'pinia'
import { markRaw } from 'vue'

function createEntry(snapshot, label) {
  const serialized = JSON.stringify(snapshot)
  // Keep one representation. Reading snapshot returns a detached value for
  // callers that inspect entries, without retaining a second object tree.
  return markRaw(Object.defineProperties({ serialized, label, bytes: serialized.length * 2 }, {
    snapshot: { get() { return JSON.parse(this.serialized) } },
  }))
}

export const useHistoryStore = defineStore('history', {
  state: () => ({ undoStack: [], redoStack: [], limit: 50, byteLimit: 16 * 1024 * 1024 }),
  getters: {
    canUndo: (state) => state.undoStack.length > 0,
    canRedo: (state) => state.redoStack.length > 0,
    retainedBytes: (state) => [...state.undoStack, ...state.redoStack].reduce((total, entry) => total + entry.bytes, 0),
  },
  actions: {
    trim(preferred) {
      const other = preferred === this.undoStack ? this.redoStack : this.undoStack
      // Preserve the nearest undo/redo even if that single snapshot exceeds
      // the budget. Discard older states first; both stacks share the budget.
      while (this.undoStack.length + this.redoStack.length > Math.max(1, this.limit)
        || this.retainedBytes > this.byteLimit) {
        if (other.length) other.shift()
        else if (preferred.length > 1) preferred.shift()
        else break
      }
    },
    push(snapshot, label = '编辑') {
      const entry = createEntry(snapshot, label)
      if (this.undoStack.at(-1)?.serialized === entry.serialized) return
      this.undoStack.push(entry)
      this.redoStack = []
      this.trim(this.undoStack)
    },
    undo(current) {
      const entry = this.undoStack.pop()
      if (!entry) return null
      this.redoStack.push(createEntry(current, entry.label))
      this.trim(this.redoStack)
      return entry.snapshot
    },
    redo(current) {
      const entry = this.redoStack.pop()
      if (!entry) return null
      this.undoStack.push(createEntry(current, entry.label))
      this.trim(this.undoStack)
      return entry.snapshot
    },
    clear() {
      this.undoStack = []
      this.redoStack = []
    },
  },
})
