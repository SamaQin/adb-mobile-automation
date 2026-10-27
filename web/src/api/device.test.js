import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { connectDevice, deviceStreamUrl, disconnectDevice, enableWirelessAdb, fetchDevices, fetchDeviceState, fetchScreenshot, pairDevice, selectDevice } from './device.js'

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, headers: new Headers({ 'content-type': 'application/json' }), json: async () => ({ devices: [], selected_serial: null, message: 'ok' }), blob: async () => new Blob(['image']) }))
})
afterEach(() => vi.unstubAllGlobals())

it('fetches device lists without caching and preserves selected_serial', async () => {
  expect(await fetchDevices()).toEqual({ devices: [], selected_serial: null, message: 'ok' })
  expect(fetch).toHaveBeenCalledWith('/api/device/devices', expect.objectContaining({ cache: 'no-store' }))
})

it.each([
  [connectDevice, { host: '10.0.35.91', port: 5555 }, 'connect', { host: '10.0.35.91', port: 5555 }],
  [pairDevice, { host: '10.0.35.91', port: 39999, code: '012345' }, 'pair', { host: '10.0.35.91', port: 39999, code: '012345' }],
  [selectDevice, 'usb-phone', 'select', { serial: 'usb-phone' }],
  [disconnectDevice, '10.0.35.91:5555', 'disconnect', { serial: '10.0.35.91:5555' }],
  [enableWirelessAdb, 5555, 'tcpip', { port: 5555 }],
])('posts the exact device contract for %s', async (call, input, endpoint, body) => {
  await call(input)
  expect(fetch).toHaveBeenCalledWith(`/api/device/${endpoint}`, expect.objectContaining({ method: 'POST', body: JSON.stringify(body) }))
})

it('preserves existing state and stream/screenshot API behavior', async () => {
  await fetchDeviceState()
  expect(fetch).toHaveBeenCalledWith('/api/device/state', expect.any(Object))
  expect(deviceStreamUrl('stream-token', 'h264')).toBe('/api/device/stream?stream=stream-token&codec=h264')
  await fetchScreenshot(720, 'jpeg')
  expect(fetch).toHaveBeenLastCalledWith('/api/device/screenshot?max_width=720&format=jpeg', expect.objectContaining({ cache: 'no-store' }))
})
