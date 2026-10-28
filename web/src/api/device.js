import { request, unwrap } from './client.js'

export async function fetchDeviceState() {
  return unwrap(await request('/api/device/state'), ['device'])
}

export function fetchDevices() {
  return request('/api/device/devices', { cache: 'no-store' })
}

export function connectDevice({ host, port }) {
  return request('/api/device/connect', { method: 'POST', body: { host, port } })
}

export function pairDevice({ host, port, code }) {
  return request('/api/device/pair', { method: 'POST', body: { host, port, code } })
}

export function enableWirelessAdb(port = 5555) {
  return request('/api/device/tcpip', { method: 'POST', body: { port } })
}

export function selectDevice(serial) {
  return request('/api/device/select', { method: 'POST', body: { serial } })
}

export function disconnectDevice(serial) {
  return request('/api/device/disconnect', { method: 'POST', body: { serial } })
}

export function screenshotUrl(maxWidth, format = 'png') {
  const params = new URLSearchParams()
  if (maxWidth) params.set('max_width', String(maxWidth))
  if (format && format !== 'png') params.set('format', format)
  const query = params.toString()
  return `/api/device/screenshot${query ? `?${query}` : ''}`
}

export async function fetchScreenshot(maxWidth, format = 'png') {
  return request(screenshotUrl(maxWidth, format), {
    responseType: 'blob',
    cache: 'no-store',
  })
}

export function deviceStreamUrl(token = '', codec = 'jpeg') {
  const params = new URLSearchParams()
  if (token) params.set('stream', token)
  if (codec === 'h264') params.set('codec', 'h264')
  const query = params.toString()
  return `/api/device/stream${query ? `?${query}` : ''}`
}

export async function fetchStreamStatus() {
  return request('/api/device/stream/status', { cache: 'no-store' })
}

export function sendDeviceInput(input) {
  return request('/api/device/input', { method: 'POST', body: input })
}
