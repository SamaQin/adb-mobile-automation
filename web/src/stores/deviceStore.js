import { defineStore } from 'pinia'
import { connectDevice, disconnectDevice, enableWirelessAdb, fetchDevices, fetchDeviceState, pairDevice, selectDevice } from '../api/device.js'

const pendingChecks = new WeakMap()
const pendingLists = new WeakMap()
const revisions = new WeakMap()
const listRevisions = new WeakMap()
const listRevision = (store) => listRevisions.get(store) || 0
const advanceList = (store) => listRevisions.set(store, listRevision(store) + 1)
const revision = (store) => revisions.get(store) || 0
const advance = (store) => revisions.set(store, revision(store) + 1)

export const useDeviceStore = defineStore('device', {
  state: () => ({
    connected: false, resolution: null, state: 'unknown', checking: false, error: '',
    serial: null, transport: null, selectedSerial: null, devices: [],
    refreshing: false, operationBusy: false,
  }),
  actions: {
    apply(payload = {}) {
      advance(this)
      const state = payload.state || payload.status
      this.connected = payload.connected ?? state === 'device'
      this.resolution = payload.resolution || payload.screen_resolution || null
      this.state = state || (this.connected ? 'device' : 'offline')
      this.error = payload.error || payload.detail || ''
      this.serial = payload.serial ?? null
      this.transport = payload.transport ?? null
      if ('selected_serial' in payload || 'selectedSerial' in payload) {
        this.selectedSerial = payload.selected_serial ?? payload.selectedSerial ?? null
      } else if ('serial' in payload) this.selectedSerial = payload.serial ?? null
    },
    applyDevices(payload = {}) {
      if (Array.isArray(payload.devices)) this.devices = payload.devices
      if ('selected_serial' in payload || 'selectedSerial' in payload) {
        this.selectedSerial = payload.selected_serial ?? payload.selectedSerial ?? null
      }
    },
    check() {
      if (this.operationBusy) return Promise.resolve(this.connected)
      const current = revision(this)
      const pending = pendingChecks.get(this)
      if (pending?.revision === current) return pending.promise
      this.checking = true
      const request = Promise.resolve().then(fetchDeviceState).then((payload) => {
        if (revision(this) === current) this.apply(payload)
        return this.connected
      }).catch((error) => {
        if (revision(this) === current) {
          this.apply({ state: 'error', error: error.message })
          throw error
        }
        return this.connected
      }).finally(() => {
        if (pendingChecks.get(this)?.promise === request) {
          pendingChecks.delete(this)
          this.checking = false
        }
      })
      pendingChecks.set(this, { revision: current, promise: request })
      return request
    },
    refreshDevices() {
      if (this.operationBusy) return Promise.resolve(this.devices)
      const current = listRevision(this)
      const pending = pendingLists.get(this)
      if (pending?.revision === current) return pending.promise
      this.refreshing = true
      const request = Promise.resolve().then(fetchDevices).then((payload) => {
        if (listRevision(this) === current) this.applyDevices(payload)
        return this.devices
      }).finally(() => {
        if (pendingLists.get(this)?.promise === request) {
          pendingLists.delete(this)
          this.refreshing = false
        }
      })
      pendingLists.set(this, { revision: current, promise: request })
      return request
    },
    async operate(action, input) {
      if (this.operationBusy) throw new Error('设备操作正在进行，请稍候。')
      this.operationBusy = true
      advance(this)
      advanceList(this)
      try {
        const payload = await action(input)
        if (payload.device) this.apply(payload.device)
        advance(this)
        this.applyDevices(payload)
        return payload
      } finally {
        advance(this)
        this.operationBusy = false
      }
    },
    connect(target) { return this.operate(connectDevice, target) },
    pair(target) { return this.operate(pairDevice, target) },
    enableWireless(port = 5555) { return this.operate(enableWirelessAdb, port) },
    select(serial) { return this.operate(selectDevice, serial) },
    disconnect(serial) { return this.operate(disconnectDevice, serial) },
  },
})
