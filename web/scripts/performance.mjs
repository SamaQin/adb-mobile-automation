import { chromium } from '@playwright/test'

// Browser-only fixtures: never read or save a real config, and never mutate the server.
// Run: PLAYWRIGHT_BASE_URL=http://127.0.0.1:8002 node scripts/performance.mjs
const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8002'
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) })
const results = { baseURL, browser: browser.version(), layouts: [], workloads: [], blockedMutations: [], errors: [] }
const fixture = (count, definition) => ({
  version: 2, acceleration: 'cpu', selected_preset_id: `perf-${count}-a`,
  presets: ['a', 'b'].map((suffix) => ({
    id: `perf-${count}-${suffix}`, name: `性能验证 ${count} ${suffix}`, loop_count: 1,
    steps: Array.from({ length: count }, (_, index) => ({
      id: `perf-${suffix}-${index}`, name: `步骤 ${index + 1}`, kind: definition.key,
      enabled: true, on_failure: 'stop', depends_on: [],
      params: Object.fromEntries(definition.fields.map((field) => [field.key, structuredClone(field.default)])),
    })),
  })),
})

async function stores(page, operation, data) {
  return page.evaluate(({ operation, data }) => {
    const app = document.querySelector('#app').__vue_app__
    const pinia = app.config.globalProperties.$pinia || app._instance?.proxy?.$pinia
    const config = pinia._s.get('config')
    const ui = pinia._s.get('ui')
    if (operation === 'switch') config.selectPreset(data)
    if (operation === 'select') ui.selectNode(data)
    return { preset: config.selectedPreset.id, definitions: config.definitions.length }
  }, { operation, data })
}

async function edgeState(page) {
  return page.evaluate(() => {
    const paths = [...document.querySelectorAll('.vue-flow__edge-path')]
    return { count: paths.length, invalid: paths.filter((path) => !path.getAttribute('d') || /NaN|Infinity/.test(path.getAttribute('d'))).length }
  })
}

async function waitEdges(page, count, suffix = 'a') {
  try {
    await page.waitForFunction(({ count, suffix }) => {
      const paths = [...document.querySelectorAll('.vue-flow__edge-path')]
      return paths.length === count && paths.every((path) => path.getAttribute('d')
        && !/NaN|Infinity/.test(path.getAttribute('d'))
        && path.closest('.vue-flow__edge')?.dataset.id?.includes(`perf-${suffix}-`))
    }, { count, suffix }, { timeout: 10000 })
    return { ready: true, ...await edgeState(page) }
  } catch {
    return { ready: false, ...await edgeState(page) }
  }
}

async function layout(page) {
  const geometry = await page.evaluate(() => {
    const rect = (selector) => {
      const r = document.querySelector(selector).getBoundingClientRect()
      return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom }
    }
    const topbar = document.querySelector('.topbar')
    const boxes = Object.fromEntries(['.topbar', '.palette', '.flow-canvas', '.properties', '.log-panel'].map((s) => [s.slice(1), rect(s)]))
    return {
      ...boxes,
      documentOverflow: document.documentElement.scrollWidth > innerWidth,
      toolbarOverflow: topbar.scrollWidth > topbar.clientWidth,
      toolbarControlsOutside: [...topbar.querySelectorAll('button,select,input')].filter((el) => {
        const r = el.getBoundingClientRect()
        return r.width && (r.left < 0 || r.right > innerWidth || r.top < 0 || r.bottom > innerHeight)
      }).map((el) => el.title || el.getAttribute('aria-label') || el.tagName),
    }
  })
  geometry.noWorkspaceOverlap = geometry.palette.right <= geometry['flow-canvas'].x + 1
    && geometry['flow-canvas'].right <= geometry.properties.x + 1
    && geometry['flow-canvas'].bottom <= geometry['log-panel'].y + 1
    && geometry.topbar.bottom <= geometry['flow-canvas'].y + 1
  const controls = page.locator('.properties input, .properties select, .properties .form-actions button')
  geometry.propertyControls = await controls.count()
  geometry.unreachablePropertyControls = []
  for (let i = 0; i < await controls.count(); i++) {
    const control = controls.nth(i)
    await control.scrollIntoViewIfNeeded()
    const reachable = await control.evaluate((el) => {
      const r = el.getBoundingClientRect()
      const panel = el.closest('.properties-scroll').getBoundingClientRect()
      const hit = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)
      return r.x >= 0 && r.right <= innerWidth && r.y >= panel.y - 1 && r.bottom <= panel.bottom + 1 && (hit === el || el.contains(hit))
    })
    if (!reachable) geometry.unreachablePropertyControls.push(i)
  }
  return geometry
}

// Sample only animation frames and final observer state; do not force every mutation to layout.
async function measureEdit(page, kind, parameterKey) {
  return page.evaluate(async ({ kind, parameterKey }) => {
    const app = document.querySelector('#app').__vue_app__
    const pinia = app.config.globalProperties.$pinia || app._instance?.proxy?.$pinia
    const config = pinia._s.get('config')
    const step = config.selectedPreset.steps[0]
    const originalEdges = [...document.querySelectorAll('.vue-flow__edge-path')]
    let removedPaths = 0
    let frames = 0
    let minEdges = originalEdges.length
    let invalidFrames = 0
    const observer = new MutationObserver((records) => {
      for (const record of records) for (const node of record.removedNodes) {
        if (node.nodeType === 1) removedPaths += Number(node.matches?.('.vue-flow__edge-path')) + (node.querySelectorAll?.('.vue-flow__edge-path').length || 0)
      }
    })
    observer.observe(document.querySelector('.vue-flow'), { subtree: true, childList: true })
    const start = performance.now()
    config.mutateStep(step.id, (draft) => {
      if (kind === 'rename') draft.name = `改名 ${start}`
      else draft.params[parameterKey] = Number(draft.params[parameterKey] || 0) + 1
    })
    const actionMs = performance.now() - start
    await Promise.resolve()
    const microtaskMs = performance.now() - start
    let firstPaintMs
    await new Promise((resolve) => {
      const sample = () => {
        frames++
        firstPaintMs ??= performance.now() - start
        const paths = [...document.querySelectorAll('.vue-flow__edge-path')]
        minEdges = Math.min(minEdges, paths.length)
        if (paths.some((path) => /NaN|Infinity/.test(path.getAttribute('d') || '') || !path.getAttribute('d'))) invalidFrames++
        if (performance.now() - start >= 250 && frames >= 3) resolve()
        else requestAnimationFrame(sample)
      }
      requestAnimationFrame(sample)
    })
    observer.disconnect()
    return {
      actionMs, microtaskMs, firstPaintMs, frames, minEdges, invalidFrames, removedPaths,
      preservedEdgeElements: originalEdges.filter((edge) => edge.isConnected).length,
      labelUpdated: kind !== 'rename' || document.querySelector(`[data-id="${step.id}"]`)?.textContent.includes(step.name),
    }
  }, { kind, parameterKey })
}

try {
  const discovery = await browser.newContext()
  const response = await discovery.request.get(`${baseURL}/api/step-definitions`)
  if (!response.ok()) throw new Error(`Step definitions HTTP ${response.status()}`)
  const payload = await response.json()
  const definitions = payload.definitions || payload.step_definitions || payload
  const definition = definitions.find((def) => def.key === 'tap') || definitions.find((def) => def.fields.some((f) => ['int', 'float'].includes(f.kind)))
  const parameterKey = definition.fields.find((field) => ['int', 'float'].includes(field.kind)).key
  results.definition = { key: definition.key, count: definitions.length, parameterKey }
  await discovery.close()

  for (const count of [100, 500]) {
    const context = await browser.newContext({ viewport: { width: 1366, height: 768 } })
    await context.route('**/api/**', async (route) => {
      const request = route.request()
      const path = new URL(request.url()).pathname
      if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
        results.blockedMutations.push({ method: request.method(), path })
        return route.abort('blockedbyclient')
      }
      if (path === '/api/config') return route.fulfill({ json: fixture(count, definition) })
      return route.continue()
    })
    await context.addInitScript(() => {
      window.__edgeAudit = { invalidObserved: 0, firstPathsMs: null, maxPaths: 0 }
      new MutationObserver(() => {
        const paths = [...document.querySelectorAll('.vue-flow__edge-path')]
        if (paths.length) window.__edgeAudit.firstPathsMs ??= performance.now()
        window.__edgeAudit.maxPaths = Math.max(window.__edgeAudit.maxPaths, paths.length)
        window.__edgeAudit.invalidObserved += paths.filter((path) => !path.getAttribute('d') || /NaN|Infinity/.test(path.getAttribute('d'))).length
      }).observe(document, { subtree: true, childList: true, attributes: true, attributeFilter: ['d'] })
    })
    const page = await context.newPage()
    page.on('pageerror', (error) => results.errors.push(error.message))
    const started = Date.now()
    await page.goto(baseURL, { waitUntil: 'domcontentloaded' })
    await page.locator('.vue-flow__node-step').first().waitFor()
    const initialEdges = await waitEdges(page, count)
    const workload = { count, initialEdges, initialReadyMs: Date.now() - started, initialAudit: await page.evaluate(() => window.__edgeAudit) }
    await stores(page, 'select', 'perf-a-0')
    await page.locator('.step-form').waitFor()
    if (count === 100) {
      for (const viewport of [{ width: 1366, height: 768 }, { width: 1280, height: 800 }, { width: 1100, height: 700 }]) {
        await page.setViewportSize(viewport)
        results.layouts.push({ viewport, ...await layout(page) })
      }
      await page.setViewportSize({ width: 1366, height: 768 })
    }
    workload.edits = []
    for (const kind of ['rename', 'parameter']) {
      for (let repeat = 0; repeat < 3; repeat++) workload.edits.push({ kind, repeat, ...await measureEdit(page, kind, parameterKey) })
    }
    workload.presetSwitches = []
    for (const suffix of ['b', 'a']) {
      const start = Date.now()
      await stores(page, 'switch', `perf-${count}-${suffix}`)
      await page.locator(`.vue-flow__node-step[data-id="perf-${suffix}-0"]`).waitFor({ state: 'attached' })
      workload.presetSwitches.push({ suffix, ...(await waitEdges(page, count, suffix)), elapsedMs: Date.now() - start })
    }
    workload.finalAudit = await page.evaluate(() => window.__edgeAudit)
    const transform = () => page.locator('.vue-flow__transformationpane').getAttribute('style')
    const beforeZoom = await transform()
    await page.locator('.canvas-toolbar button[title="放大"]').click()
    await page.waitForTimeout(350)
    const afterZoom = await transform()
    workload.zoom = { changed: beforeZoom !== afterZoom, before: beforeZoom, after: afterZoom, edges: await edgeState(page) }
    // Fit the long chain, then drag a visible step (minimum zoom may clip its ends).
    await page.locator('.canvas-toolbar button[title="适应视图"]').click()
    await page.waitForTimeout(350)
    const visibleId = await page.evaluate(() => {
      const canvas = document.querySelector('.flow-canvas').getBoundingClientRect()
      return [...document.querySelectorAll('.vue-flow__node-step')].find((node) => {
        const r = node.getBoundingClientRect()
        return r.top > canvas.top + 70 && r.bottom < canvas.bottom - 70 && r.left > canvas.left + 20 && r.right < canvas.right - 20
      })?.dataset.id
    })
    const node = page.locator(`.vue-flow__node-step[data-id="${visibleId}"]`)
    const beforeDrag = visibleId ? await node.boundingBox() : null
    const canvas = await page.locator('.flow-canvas').boundingBox()
    if (beforeDrag && beforeDrag.y >= canvas.y && beforeDrag.y + beforeDrag.height <= canvas.y + canvas.height) {
      await page.mouse.move(beforeDrag.x + beforeDrag.width / 2, beforeDrag.y + beforeDrag.height / 2)
      await page.mouse.down()
      await page.mouse.move(beforeDrag.x + beforeDrag.width / 2 + 30, beforeDrag.y + beforeDrag.height / 2 + 20, { steps: 6 })
      await page.mouse.up()
      const afterDrag = await node.boundingBox()
      workload.drag = { moved: Math.abs(afterDrag.x - beforeDrag.x) > 10, before: beforeDrag, after: afterDrag, edges: await edgeState(page) }
    } else workload.drag = { moved: false, reason: 'No step fully inside canvas after fit' }
    results.workloads.push(workload)
    await context.close()
  }
} catch (error) {
  results.errors.push(error.stack || error.message)
  process.exitCode = 1
} finally {
  await browser.close()
  for (const item of results.layouts) {
    if (item.toolbarOverflow || item.documentOverflow || item.toolbarControlsOutside.length
      || !item.noWorkspaceOverlap || item.unreachablePropertyControls.length) {
      results.errors.push(`Layout or control reachability failed at ${item.viewport.width}x${item.viewport.height}`)
    }
  }
  for (const item of results.workloads) {
    if (!item.initialEdges.ready || item.initialAudit.invalidObserved || item.finalAudit.invalidObserved
      || item.presetSwitches.some((entry) => !entry.ready)
      || item.edits.some((entry) => entry.minEdges !== item.count || entry.invalidFrames || entry.removedPaths || !entry.labelUpdated)
      || !item.zoom.changed || !item.drag.moved) {
      results.errors.push(`Graph validation failed for ${item.count} steps`)
    }
  }
  if (results.blockedMutations.length) results.errors.push('Unexpected attempted server mutation')
  if (results.errors.length) process.exitCode = 1
  console.log(JSON.stringify(results, null, 2))
}
