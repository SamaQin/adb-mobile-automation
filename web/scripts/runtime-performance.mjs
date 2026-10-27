import { chromium } from '@playwright/test'

// Synthetic client-only events. API writes are blocked, events WS is mocked,
// and no run, device command, or config save reaches the server.
// Build once with the other frontend changes, serve the disposable fixture,
// then PLAYWRIGHT_BASE_URL=http://127.0.0.1:8002 node scripts/runtime-performance.mjs.
const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8002'
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) })
const results = { baseURL, browser: browser.version(), workloads: [], errors: [], blockedMutations: [] }

try {
  const discovery = await browser.newContext()
  const response = await discovery.request.get(`${baseURL}/api/step-definitions`)
  if (!response.ok()) throw new Error(`Definitions HTTP ${response.status()}`)
  const payload = await response.json()
  const definitions = payload.definitions || payload.step_definitions || payload
  const definition = definitions.find((item) => item.key === 'wait') || definitions[0]
  await discovery.close()

  for (const count of [100, 500]) {
    const context = await browser.newContext({ viewport: { width: 1366, height: 768 } })
    await context.route('**/api/**', (route) => {
      const request = route.request()
      const path = new URL(request.url()).pathname
      if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
        results.blockedMutations.push({ method: request.method(), path })
        return route.abort('blockedbyclient')
      }
      if (path === '/api/config') return route.fulfill({ json: {
        version: 2, acceleration: 'cpu', selected_preset_id: 'runtime-perf',
        presets: [{ id: 'runtime-perf', name: 'Runtime stress', loop_count: 1,
          steps: Array.from({ length: count }, (_, index) => ({
            id: `step-${index}`, name: `Step ${index}`, kind: definition.key,
            enabled: true, on_failure: 'stop', depends_on: [],
            params: Object.fromEntries(definition.fields.map((field) => [field.key, structuredClone(field.default)])),
          })),
        }],
      } })
      return route.continue()
    })
    await context.routeWebSocket('**/ws/events', (socket) => {
      socket.send(JSON.stringify({ type: 'status', data: { state: 'idle' } }))
    })
    const page = await context.newPage()
    page.on('pageerror', (error) => results.errors.push(error.message))
    await page.goto(baseURL)
    await page.waitForFunction((count) => document.querySelectorAll('.vue-flow__edge-path').length === count
      && [...document.querySelectorAll('.vue-flow__edge-path')].every((path) => path.getAttribute('d') && !/NaN|Infinity/.test(path.getAttribute('d'))), count)

    const workload = await page.evaluate(async (count) => {
      const pinia = document.querySelector('#app').__vue_app__.config.globalProperties.$pinia
      const run = pinia._s.get('run')
      const ui = pinia._s.get('ui')
      run.socket?.close()
      let seq = 0
      const event = (type, data) => run.handleEvent({ type, data, server_id: 'runtime-perf', run_id: 'runtime-perf', seq: ++seq })
      const paint = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))
      const check = (condition, message) => { if (!condition) throw new Error(message) }
      event('status', { state: 'running', root_cycle: 1, node_states: {} })
      await paint()
      const originalEdges = [...document.querySelectorAll('.vue-flow__edge-path')]
      const canvasRect = document.querySelector('.flow-canvas').getBoundingClientRect()
      const nodes = [...document.querySelectorAll('.vue-flow__node')]
      const visibleNodeCount = nodes.filter((node) => {
        const rect = node.getBoundingClientRect()
        return rect.right > canvasRect.left && rect.left < canvasRect.right && rect.bottom > canvasRect.top && rect.top < canvasRect.bottom
      }).length
      const batches = []
      let previousFrame = performance.now()
      let maxFrameGapMs = 0
      let invalidFrames = 0
      let frames = 0
      let sampling = true
      const sample = (now) => {
        maxFrameGapMs = Math.max(maxFrameGapMs, now - previousFrame)
        previousFrame = now
        frames++
        const paths = [...document.querySelectorAll('.vue-flow__edge-path')]
        if (paths.length !== count || paths.some((path) => !path.getAttribute('d') || /NaN|Infinity/.test(path.getAttribute('d')))) invalidFrames++
        if (sampling) requestAnimationFrame(sample)
      }
      requestAnimationFrame(sample)
      const formatTime = Date.prototype.toLocaleTimeString
      let formattedRows = 0
      Date.prototype.toLocaleTimeString = function (...args) { formattedRows++; return formatTime.apply(this, args) }
      const started = performance.now()
      try {
        for (let batch = 0; batch < 50; batch++) {
          const start = performance.now()
          for (let i = 0; i < 20; i++) {
            const index = (batch * 20 + i) % count
            event('step', { step_id: `step-${index}`, frame_id: 'root', state: 'running' })
            event('log', { text: `Progress ${batch * 20 + i}`, step_id: `step-${index}` })
            event('step', { step_id: `step-${index}`, frame_id: 'root', state: 'done' })
          }
          batches.push(performance.now() - start)
          await paint()
        }
        const elapsedMs = performance.now() - started
        check(run.logs.length === 500, 'Log cap failed')
        const scroller = document.querySelector('.log-scroll')
        check(scroller.scrollHeight - scroller.clientHeight - scroller.scrollTop <= 2, 'Full log buffer stopped following')
        check(formattedRows === 1000, `Existing rows reformatted: ${formattedRows}`)
        scroller.scrollTop = 1000
        scroller.dispatchEvent(new Event('scroll'))
        const row = [...scroller.children].find((node) => node.offsetTop + node.offsetHeight > scroller.scrollTop)
        const anchor = { id: row.dataset.logId, offset: row.offsetTop - scroller.scrollTop }
        for (let i = 0; i < 10; i++) event('log', { text: `Historical view ${i}` })
        await paint()
        const sameRow = [...scroller.children].find((node) => node.dataset.logId === anchor.id)
        check(Math.abs(sameRow.offsetTop - scroller.scrollTop - anchor.offset) <= 2, 'Reading history lost its anchor')
        check(scroller.scrollHeight - scroller.clientHeight - scroller.scrollTop > 100, 'Reading history was pulled to the bottom')
        ui.logCollapsed = true
        await paint()
        const beforeHidden = formattedRows
        for (let i = 0; i < 1000; i++) event('log', { text: `Collapsed ${i}` })
        await paint()
        check(formattedRows === beforeHidden, 'Collapsed logs formatted rows')
        check(!document.querySelector('.log-scroll'), 'Collapsed log scroller still mounted')
        ui.logCollapsed = false
        await paint()
        event('step', { step_id: 'step-0', frame_id: 'root', state: 'running' })
        await paint()
        check(document.querySelectorAll('.vue-flow__edge.animated').length > 0, 'Registered edges did not animate')
        event('status', { state: 'running', reset_frame_id: 'root' })
        event('step', { step_id: 'step-1', frame_id: 'child', state: 'failed', error: 'final failure' })
        await paint()
        check(document.querySelector('[data-id="step-0"] .step-node')?.classList.contains('state-idle'), 'Frame reset lost idle state')
        event('status', { state: 'running', root_cycle: 2 })
        event('finished', { status: 'failed', node_states: { 'step-1': { state: 'failed', error: 'final failure' } } })
        await paint()
        check(document.querySelector('[data-id="step-1"] .step-node')?.classList.contains('state-failed'), 'Finished snapshot lost terminal state')
        check(document.querySelectorAll('.vue-flow__edge.animated').length === 0, 'Finished edges still animated')
        check(run.logs.length === 500 && new Set(run.logs.map((line) => line.id)).size === 500, 'Finished log cap or unique ids failed')
        check(invalidFrames === 0 && originalEdges.every((edge) => edge.isConnected), 'Runtime events damaged graph edges')
        return { count, eventCount: seq, elapsedMs, maxBatchMs: Math.max(...batches), meanBatchMs: batches.reduce((a, b) => a + b, 0) / batches.length,
          maxFrameGapMs, frames, invalidFrames, renderedNodeCount: nodes.length, visibleNodeCount,
          fullBufferFollow: true, historyAnchorPreserved: true, collapsedFormatWork: 0, terminalAndReset: true,
          preservedEdges: originalEdges.length }
      } finally {
        sampling = false
        Date.prototype.toLocaleTimeString = formatTime
      }
    }, count)
    results.workloads.push(workload)
    await context.close()
  }
} catch (error) {
  results.errors.push(error.stack || error.message)
  process.exitCode = 1
} finally {
  await browser.close()
  if (results.blockedMutations.length) results.errors.push('Unexpected attempted API mutation')
  if (results.errors.length) process.exitCode = 1
  console.log(JSON.stringify(results, null, 2))
}
