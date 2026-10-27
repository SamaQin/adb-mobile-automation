import { defineStore } from 'pinia'
import { markRaw } from 'vue'
import { fetchTemplates } from '../api/templates.js'

const requests = new WeakMap()
const FRESH_MS = 5000

export const useTemplateStore = defineStore('templates', {
  state: () => ({ items: [], loadedAt: 0, loading: false, generation: 0, error: '' }),
  getters: {
    byName: (state) => new Map(state.items.map((item) => [item.name || item.file, item])),
  },
  actions: {
    invalidate() {
      this.generation += 1
      this.loadedAt = 0
    },
    load({ force = false } = {}) {
      const pending = requests.get(this)
      if (pending?.generation === this.generation) return pending.promise
      if (!force && this.loadedAt && Date.now() - this.loadedAt < FRESH_MS) return Promise.resolve(this.items)
      const generation = this.generation
      this.loading = true
      this.error = ''
      const promise = Promise.resolve().then(fetchTemplates).then((items) => {
        if (generation !== this.generation) return this.load()
        // The catalog is replaced on refresh; individual metadata records are immutable.
        this.items = markRaw(items)
        this.loadedAt = Date.now()
        return items
      }).catch((error) => {
        if (generation === this.generation) this.error = error.message
        throw error
      }).finally(() => {
        if (requests.get(this)?.promise === promise) {
          requests.delete(this)
          this.loading = false
        }
      })
      requests.set(this, { generation, promise })
      return promise
    },
  },
})
