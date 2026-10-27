import { request, unwrap } from './client.js'

export async function fetchDeviceState() {
  return unwrap(await request('/api/device/state'), ['device'])
}

export function screenshotUrl(maxWidth) {
  const query = maxWidth ? `?max_width=${encodeURIComponent(maxWidth)}` : ''
  return `/api/device/screenshot${query}`
}

export async function fetchScreenshot(maxWidth) {
  return request(screenshotUrl(maxWidth), { responseType: 'blob' })
}
