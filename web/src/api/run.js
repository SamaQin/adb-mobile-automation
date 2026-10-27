import { request, unwrap } from './client.js'

export async function startRun(presetId) {
  return unwrap(await request('/api/run', { method: 'POST', body: { preset_id: presetId } }), ['run'])
}

export async function stopRun() {
  return unwrap(await request('/api/stop', { method: 'POST' }), ['run'])
}

export async function fetchRunStatus() {
  return unwrap(await request('/api/run/status'), ['run'])
}
