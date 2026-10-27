import { request, unwrap } from './client.js'

export async function exportPresetArchive(presetId) {
  return request(`/api/archive/export?preset_id=${encodeURIComponent(presetId)}`, { responseType: 'blob' })
}

export async function importPresetArchive(file) {
  const form = new FormData()
  form.append('file', file)
  return unwrap(await request('/api/archive/import', { method: 'POST', body: form }), ['config', 'preset', 'result'])
}
