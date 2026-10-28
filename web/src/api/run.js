import { request, unwrap } from './client.js'

export async function startRun(presetId, startStepId = null) {
  const body = { preset_id: presetId }
  if (startStepId) body.start_step_id = startStepId
  return unwrap(await request('/api/run', { method: 'POST', body }), ['run'])
}

export async function stopRun() {
  return unwrap(await request('/api/stop', { method: 'POST' }), ['run'])
}

export async function fetchRunStatus() {
  return unwrap(await request('/api/run/status'), ['run'])
}
