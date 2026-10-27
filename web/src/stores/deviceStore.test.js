import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { useDeviceStore } from './deviceStore.js'
import { fetchDeviceState } from '../api/device.js'

vi.mock('../api/device.js', () => ({ fetchDeviceState: vi.fn() }))
beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks() })

it('coalesces concurrent checks without permanently caching device state', async () => {
  const store = useDeviceStore()
  let resolve
  fetchDeviceState.mockImplementationOnce(() => new Promise((done) => { resolve = done }))
  const first = store.check()
  const second = store.check()
  await Promise.resolve()
  resolve({ connected: true, state: 'device', resolution: { width: 100, height: 60 } })
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
