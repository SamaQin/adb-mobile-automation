import { request, unwrap } from './client.js'

export async function fetchConfig() {
  return unwrap(await request('/api/config'), ['config'])
}

export async function saveConfig(config) {
  return unwrap(await request('/api/config', { method: 'PUT', body: config }), ['config'])
}

export async function fetchStepDefinitions() {
  const payload = await request('/api/step-definitions')
  return unwrap(payload, ['definitions', 'step_definitions']) || []
}

export async function duplicatePreset(presetId) {
  return unwrap(await request(`/api/presets/${encodeURIComponent(presetId)}/duplicate`, { method: 'POST' }), ['preset', 'config'])
}

export async function fetchPresetReferences(presetId) {
  const payload = await request(`/api/presets/${encodeURIComponent(presetId)}/references`)
  return unwrap(payload, ['references']) || []
}

export async function setAcceleration(acceleration) {
  return unwrap(await request('/api/settings/acceleration', {
    method: 'PUT',
    body: { acceleration },
  }), ['acceleration', 'config'])
}

export async function scaleStep(step, targetResolution) {
  return unwrap(await request('/api/coords/scale', {
    method: 'POST',
    body: { step, target_resolution: targetResolution },
  }), ['step'])
}
