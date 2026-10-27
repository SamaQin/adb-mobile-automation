import { request, unwrap } from './client.js'

export async function fetchDeviceState() {
  return unwrap(await request('/api/device/state'), ['device'])
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
