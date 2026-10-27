import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { useDeviceStore } from './deviceStore.js'
import { connectDevice, disconnectDevice, enableWirelessAdb, fetchDevices, fetchDeviceState, pairDevice, selectDevice } from '../api/device.js'

vi.mock('../api/device.js', () => ({
  fetchDeviceState: vi.fn(), fetchDevices: vi.fn(), connectDevice: vi.fn(),
  pairDevice: vi.fn(), selectDevice: vi.fn(), disconnectDevice: vi.fn(), enableWirelessAdb: vi.fn(),
}))
beforeEach(() => { setActivePinia(createPinia()); vi.resetAllMocks() })

function deferred() {
  let resolve, reject
  const promise = new Promise((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
const connected = { connected: true, state: 'device', serial: '10.0.35.91:5555', transport: 'wireless', resolution: { width: 100, height: 60 } }
const result = { device: connected, devices: [{ serial: connected.serial, state: 'device', transport: 'wireless' }], selected_serial: connected.serial, message: '已连接' }

it('coalesces concurrent checks without permanently caching device state', async () => {
  const store = useDeviceStore()
  const pending = deferred()
  fetchDeviceState.mockReturnValueOnce(pending.promise)
  const first = store.check()
  const second = store.check()
  await Promise.resolve()
  pending.resolve({ connected: true, state: 'device', resolution: { width: 100, height: 60 } })
  expect(await first).toBe(true)
  expect(await second).toBe(true)
  expect(fetchDeviceState).toHaveBeenCalledTimes(1)
  fetchDeviceState.mockResolvedValueOnce({ connected: false, state: 'offline' })
  expect(await store.check()).toBe(false)
  expect(fetchDeviceState).toHaveBeenCalledTimes(2)
  expect(store.resolution).toBe(null)
})

it('clears stale resolution when the device request fails', async () => {
  const store = useDeviceStore()
  store.resolution = { width: 100, height: 60 }
  fetchDeviceState.mockRejectedValueOnce(new Error('disconnected'))
  await expect(store.check()).rejects.toThrow('disconnected')
  expect(store.resolution).toBe(null)
  expect(store.checking).toBe(false)
})

it('applies device identity and both selected serial spellings', () => {
  const store = useDeviceStore()
  store.apply({ ...connected, selected_serial: 'another' })
  expect(store.serial).toBe(connected.serial)
  expect(store.transport).toBe('wireless')
  expect(store.selectedSerial).toBe('another')
  store.apply({ ...connected, selectedSerial: null })
  expect(store.selectedSerial).toBe(null)
})

it.each(['connect', 'pair', 'select', 'disconnect'])('updates current state and the device list after %s', async (operation) => {
  const store = useDeviceStore()
  const api = { connect: connectDevice, pair: pairDevice, select: selectDevice, disconnect: disconnectDevice }[operation]
  api.mockResolvedValueOnce(result)
  const input = ['select', 'disconnect'].includes(operation) ? connected.serial : { host: '10.0.35.91', port: 5555, code: '123456' }
  expect(await store[operation](input)).toEqual(result)
  expect(api).toHaveBeenCalledWith(input)
  expect(store.connected).toBe(true)
  expect(store.serial).toBe(connected.serial)
  expect(store.devices).toEqual(result.devices)
  expect(store.selectedSerial).toBe(connected.serial)
  expect(store.operationBusy).toBe(false)
})

it('enables wireless ADB through USB without connecting implicitly', async () => {
  const store = useDeviceStore()
  enableWirelessAdb.mockResolvedValueOnce(result)
  await store.enableWireless(5555)
  expect(enableWirelessAdb).toHaveBeenCalledWith(5555)
  expect(connectDevice).not.toHaveBeenCalled()
  expect(store.devices).toEqual(result.devices)
})

it('keeps pairing separate from connection and preserves the returned current device state', async () => {
  const store = useDeviceStore()
  const before = { connected: false, state: 'offline', serial: null, transport: null }
  pairDevice.mockResolvedValueOnce({ device: before, devices: [], selected_serial: null, message: '已配对' })
  const payload = await store.pair({ host: '10.0.35.91', port: 39999, code: '123456' })
  expect(store.connected).toBe(false)
  expect(payload.message).toBe('已配对')
  expect(connectDevice).not.toHaveBeenCalled()
})

it.each(['resolve', 'reject'])('ignores stale check %s after a successful connect', async (completion) => {
  const store = useDeviceStore()
  const pending = deferred()
  fetchDeviceState.mockReturnValueOnce(pending.promise)
  const check = store.check()
  await Promise.resolve()
  connectDevice.mockResolvedValueOnce(result)
  await store.connect({ host: '10.0.35.91', port: 5555 })
  if (completion === 'resolve') pending.resolve({ connected: false, state: 'offline' })
  else pending.reject(new Error('old failure'))
  await check
  expect(store.connected).toBe(true)
  expect(store.serial).toBe(connected.serial)
  expect(store.error).toBe('')
  expect(store.checking).toBe(false)
})

it('ignores a check started before a newer apply and permits a fresh check', async () => {
  const store = useDeviceStore()
  const pending = deferred()
  fetchDeviceState.mockReturnValueOnce(pending.promise)
  const oldCheck = store.check()
  await Promise.resolve()
  store.apply(connected)
  fetchDeviceState.mockResolvedValueOnce(connected)
  await store.check()
  pending.resolve({ connected: false, state: 'offline' })
  await oldCheck
  expect(store.connected).toBe(true)
  expect(fetchDeviceState).toHaveBeenCalledTimes(2)
})

it('allows only one mutation at a time and releases busy after an error', async () => {
  const store = useDeviceStore()
  const pending = deferred()
  connectDevice.mockReturnValueOnce(pending.promise)
  const operation = store.connect({ host: '10.0.35.91', port: 5555 })
  await expect(store.select('usb')).rejects.toThrow('设备操作正在进行')
  expect(selectDevice).not.toHaveBeenCalled()
  expect(await store.check()).toBe(false)
  expect(fetchDeviceState).not.toHaveBeenCalled()
  pending.reject(new Error('连接失败'))
  await expect(operation).rejects.toThrow('连接失败')
  expect(store.operationBusy).toBe(false)
})

it('coalesces device list refresh and does not let stale lists replace mutation results', async () => {
  const store = useDeviceStore()
  const pending = deferred()
  fetchDevices.mockReturnValueOnce(pending.promise)
  const first = store.refreshDevices()
  const second = store.refreshDevices()
  await Promise.resolve()
  connectDevice.mockResolvedValueOnce(result)
  await store.connect({ host: '10.0.35.91', port: 5555 })
  pending.resolve({ devices: [], selected_serial: null })
  await Promise.all([first, second])
  expect(fetchDevices).toHaveBeenCalledTimes(1)
  expect(store.devices).toEqual(result.devices)
  expect(store.selectedSerial).toBe(connected.serial)
  expect(store.refreshing).toBe(false)
})

it('does not drop a list refresh when a concurrent health check completes', async () => {
  const store = useDeviceStore()
  const pending = deferred()
  fetchDevices.mockReturnValueOnce(pending.promise)
  const refresh = store.refreshDevices()
  fetchDeviceState.mockResolvedValueOnce(connected)
  await store.check()
  pending.resolve(result)
  await refresh
  expect(store.devices).toEqual(result.devices)
})
