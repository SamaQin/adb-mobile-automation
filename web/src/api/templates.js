import { request, unwrap } from './client.js'

export async function fetchTemplates() {
  const payload = await request('/api/templates')
  return unwrap(payload, ['templates', 'items']) || []
}

export function templateThumbnailUrl(name) {
  return `/api/templates/${encodeURIComponent(name)}/thumbnail`
}

export async function uploadTemplate(file) {
  const form = new FormData()
  form.append('file', file)
  return unwrap(await request('/api/templates/upload', { method: 'POST', body: form }), ['template'])
}

export async function captureTemplate(name, rect, threshold = 0.8) {
  return unwrap(await request('/api/templates/capture', {
    method: 'POST',
    body: { name, rect, threshold },
  }), ['template'])
}

export async function recaptureTemplate(name, rect, threshold = 0.8) {
  return unwrap(await request(`/api/templates/${encodeURIComponent(name)}/recapture`, {
    method: 'POST',
    body: { rect, threshold },
  }), ['template'])
}

export async function deleteTemplate(name) {
  return request(`/api/templates/${encodeURIComponent(name)}`, { method: 'DELETE' })
}
