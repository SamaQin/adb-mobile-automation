import { defineStore } from 'pinia'
import { fetchDeviceState } from '../api/device.js'

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
    async check() {
      this.checking = true
      try {
        this.apply(await fetchDeviceState())
        return this.connected
      } catch (error) {
        this.connected = false
        this.state = 'error'
        this.error = error.message
        throw error
      } finally {
        this.checking = false
      }
    },
  },
})
