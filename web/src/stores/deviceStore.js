import { defineStore } from 'pinia'
import { fetchDeviceState } from '../api/device.js'

const pendingChecks = new WeakMap()

export const useDeviceStore = defineStore('device', {
  state: () => ({ connected: false, resolution: null, state: 'unknown', checking: false, error: '' }),
  actions: {
    apply(payload = {}) {
      const state = payload.state || payload.status
      this.connected = payload.connected ?? state === 'device'
      this.resolution = payload.resolution || payload.screen_resolution || null
      this.state = state || (this.connected ? 'device' : 'offline')
      this.error = payload.error || payload.detail || ''
    },
    check() {
      if (pendingChecks.has(this)) return pendingChecks.get(this)
      this.checking = true
      const request = Promise.resolve().then(fetchDeviceState).then((payload) => {
        this.apply(payload)
        return this.connected
      }).catch((error) => {
        this.connected = false
        this.resolution = null
        this.state = 'error'
        this.error = error.message
        throw error
      }).finally(() => {
        pendingChecks.delete(this)
        this.checking = false
      })
      pendingChecks.set(this, request)
      return request
    },
  },
})
