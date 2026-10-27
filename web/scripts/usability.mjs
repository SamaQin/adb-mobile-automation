import { chromium } from '@playwright/test'
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'

const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8002'
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) })
const results = []
const output = process.env.PLAYWRIGHT_OUTPUT_DIR || 'artifacts'
await mkdir(output, { recursive: true })
try {
  for (const size of [{ width: 1366, height: 768 }, { width: 1100, height: 700 }]) {
    const context = await browser.newContext({ viewport: size })
    // This entire journey edits a browser-only draft. No user or fixture config is saved.
    await context.route('**/api/**', async (route) => {
      const request = route.request(), pathname = new URL(request.url()).pathname
      if (pathname === '/api/config') {
        if (request.method() === 'GET') return route.fulfill({ json: { version: 2, acceleration: 'cpu', selected_preset_id: 'ux', presets: [{ id: 'ux', name: '体验流程', loop_count: 1, steps: [] }] } })
        return route.fulfill({ json: request.postDataJSON() })
      }
      if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) return route.abort('blockedbyclient')
      return route.continue()
    })
    const page = await context.newPage()
    const errors = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.goto(baseURL)
    await page.locator('.canvas-welcome').waitFor()
    await page.getByRole('button', { name: '使用帮助', exact: true }).click()
    await page.getByRole('heading', { name: '快速上手' }).waitFor()
    await page.keyboard.press('Escape')
    await page.getByRole('heading', { name: '快速上手' }).waitFor({ state: 'detached' })
    const search = page.getByRole('searchbox', { name: '筛选步骤类型' })
    await search.fill('不存在的用途')
    await page.getByText('没有找到合适的步骤').waitFor()
    await page.getByRole('button', { name: '清空搜索，查看全部' }).click()
    await search.fill('等待')
    await page.locator('.palette-item').first().click()
    await page.locator('.step-form').waitFor()
    assert.equal(await page.locator('.vue-flow__node-step').count(), 1)
    await page.locator('.canvas-welcome').waitFor({ state: 'detached' })
    const numeric = page.locator('.step-form input[type=number]').first()
    await numeric.fill('-1'); await numeric.blur()
    await page.locator('.step-form [aria-invalid="true"]').waitFor()
    const seconds = await page.evaluate(() => document.querySelector('#app').__vue_app__.config.globalProperties.$pinia._s.get('config').selectedPreset.steps[0].params.seconds)
    assert.equal(seconds, 1, 'Invalid input must not overwrite the valid workflow')
    await numeric.fill('2'); await numeric.blur()
    assert.equal(await page.locator('.step-form [aria-invalid="true"]').count(), 0)
    const name = page.locator('.step-form input:not([type])').first()
    await name.fill('等待界面就绪')
    await Promise.all([
      page.waitForResponse((response) => response.url().includes('/api/config') && response.request().method() === 'PUT'),
      page.keyboard.press('Control+s'),
    ])
    const savedName = await page.evaluate(() => document.querySelector('#app').__vue_app__.config.globalProperties.$pinia._s.get('config').selectedPreset.steps[0].name)
    assert.equal(savedName, '等待界面就绪', 'Ctrl+S must commit the focused field before saving')
    await page.getByTitle('新建预设').click()
    const dialog = page.getByRole('dialog', { name: '新建预设' })
    await dialog.waitFor()
    const focused = await dialog.locator('input').evaluate((input) => input === document.activeElement)
    assert.equal(focused, true)
    await page.keyboard.press('Escape')
    await dialog.waitFor({ state: 'detached' })
    await search.fill('找图')
    await page.locator('.palette-item').first().click()
    await page.getByText('识别目标', { exact: true }).waitFor()
    assert.equal(await page.locator('.coordinate-group').count(), 0, 'Inactive retry/ROI/custom coordinates stay hidden')
    await page.getByRole('button', { name: '管理或创建模板' }).click()
    await page.getByRole('dialog', { name: '模板管理' }).waitFor()
    await page.getByTitle('关闭模板管理').click()
    await search.fill('')
    await page.waitForTimeout(350)
    await page.screenshot({ path: `${output}/usability-${size.width}x${size.height}.png`, fullPage: true })
    const bounds = await page.evaluate(() => {
      const rect = (s) => document.querySelector(s).getBoundingClientRect()
      const canvas = rect('.flow-canvas'), properties = rect('.properties'), logs = rect('.log-panel'), status = rect('.workspace-status')
      return { statusAboveCanvas: status.bottom <= canvas.top, noOverlap: canvas.right <= properties.left && canvas.bottom <= logs.top, viewportHeight: innerHeight, bottom: logs.bottom, toolbarOverflow: document.querySelector('.topbar').scrollWidth > document.querySelector('.topbar').clientWidth }
    })
    assert.equal(bounds.statusAboveCanvas && bounds.noOverlap && bounds.bottom <= size.height && !bounds.toolbarOverflow, true, JSON.stringify(bounds))
    assert.deepEqual(errors, [])
    results.push({ size, passed: true, ...bounds })
    await context.close()
  }
  console.log(JSON.stringify({ usability: results }))
} finally { await browser.close() }
