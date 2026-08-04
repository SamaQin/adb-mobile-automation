import { defineStore } from 'pinia'
import { cloneJson } from '../utils/clone.js'

const clone = cloneJson

export const useHistoryStore = defineStore('history', {
  state: () => ({ undoStack: [], redoStack: [], limit: 50 }),
  getters: {
    canUndo: (state) => state.undoStack.length > 0,
    canRedo: (state) => state.redoStack.length > 0,
  },
  actions: {
    push(snapshot, label = '编辑') {
      const previous = this.undoStack.at(-1)
      const serialized = JSON.stringify(snapshot)
      if (previous?.serialized === serialized) return
      this.undoStack.push({ snapshot: clone(snapshot), serialized, label })
      if (this.undoStack.length > this.limit) this.undoStack.shift()
      this.redoStack = []
    },
    undo(current) {
      const entry = this.undoStack.pop()
      if (!entry) return null
      this.redoStack.push({ snapshot: clone(current), serialized: JSON.stringify(current), label: entry.label })
      return clone(entry.snapshot)
    },
    redo(current) {
      const entry = this.redoStack.pop()
      if (!entry) return null
      this.undoStack.push({ snapshot: clone(current), serialized: JSON.stringify(current), label: entry.label })
      return clone(entry.snapshot)
    },
    clear() {
      this.undoStack = []
      this.redoStack = []
    },
  },
})
