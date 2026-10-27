import { chromium } from '@playwright/test'

// This check mutates only the disposable tests.e2e_web_app fixture.
const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8002'
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) })
let context
let started = false
try {
  context = await browser.newContext({ viewport: { width: 1366, height: 768 } })
  const response = await context.request.get(`${baseURL}/api/config`)
  const config = await response.json()
  const preset = config.presets?.find((item) => item.name === '浏览器联调验收')
  if (!preset) throw new Error('Runtime acceptance requires the disposable tests.e2e_web_app fixture')
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto(baseURL)
  await page.locator('.ws-state.connected').waitFor()
  const start = await context.request.post(`${baseURL}/api/run`, { data: { preset_id: preset.id } })
  if (!start.ok()) throw new Error(`Start failed: ${await start.text()}`)
  started = true
  await page.locator('.step-node.state-running').waitFor()
  const status = await context.request.get(`${baseURL}/api/run/status`).then((result) => result.json())
  if (!status.run_id || !status.server_id || !status.frames.length || !Object.values(status.node_states).some((node) => node.state === 'running')) {
    throw new Error('The running status does not contain an authoritative execution snapshot')
  }
  await page.reload()
  await page.locator('.ws-state.connected').waitFor()
  await page.locator('.step-node.state-running').waitFor()
  const readStore = () => page.evaluate(() => {
    const store = document.querySelector('#app').__vue_app__.config.globalProperties.$pinia._s.get('run')
    return { runId: store.runId, state: store.state, nodes: store.nodeStates, logs: store.logs.map((log) => log.id) }
  })
  const restored = await readStore()
  if (restored.runId !== status.run_id || !Object.values(restored.nodes).some((node) => node.state === 'running')) throw new Error('Page reload lost node state')
  await page.evaluate(() => document.querySelector('#app').__vue_app__.config.globalProperties.$pinia._s.get('run').socket.socket.close())
  await page.locator('.ws-state.disconnected').waitFor()
  await page.locator('.ws-state.connected').waitFor()
  const reconnected = await readStore()
  if (new Set(reconnected.logs).size !== reconnected.logs.length) throw new Error('Reconnect duplicated execution logs')
  if (reconnected.runId !== status.run_id) throw new Error('Reconnect changed the current run identity')
  const stop = await context.request.post(`${baseURL}/api/stop`)
  if (!stop.ok()) throw new Error(`Stop failed: ${await stop.text()}`)
  await page.getByTitle('运行当前预设').waitFor()
  started = false
  if (errors.length) throw new Error(errors.join('\n'))
  console.log(JSON.stringify({ runtime_acceptance: 'ok', reloaded: true, reconnected: true, duplicateLogs: false, runId: status.run_id }))
} finally {
  if (started && context) await context.request.post(`${baseURL}/api/stop`).catch(() => {})
  await browser.close()
}
