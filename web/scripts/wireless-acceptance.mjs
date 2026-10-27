import { chromium } from '@playwright/test'
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'

const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined })
const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8002'
const output = process.env.PLAYWRIGHT_OUTPUT_DIR || 'artifacts'
await mkdir(output, { recursive: true })
try {
  const context = await browser.newContext({ viewport: { width: 1366, height: 768 } })
  const page = await context.newPage()
  const errors = [], calls = []
  let serial = 'usb-test', connected = true
  const state = () => ({ connected, state: connected ? 'device' : 'unavailable', resolution: connected ? { width: 1080, height: 2400 } : null, serial, selected_serial: serial, transport: serial.includes(':') ? 'wireless' : 'usb' })
  const devices = () => [{ serial: 'usb-test', state: 'device', transport: 'usb', model: 'REDMAGIC' }, ...(connected && serial.includes(':') ? [{ serial, state: 'device', transport: 'wireless', model: 'REDMAGIC' }] : [])]
  page.on('pageerror', (error) => errors.push(error.message))
  await context.route('**/api/device/**', async (route) => {
    const request = route.request(), name = new URL(request.url()).pathname.split('/').at(-1)
    if (request.method() === 'GET') {
      if (name === 'state') return route.fulfill({ json: { device: state() } })
      if (name === 'devices') return route.fulfill({ json: { devices: devices(), selected_serial: serial } })
      return route.abort('blockedbyclient')
    }
    const payload = request.postDataJSON()
    calls.push({ name, ...payload })
    if (name === 'connect' && payload.port === 1234) return route.fulfill({ status: 503, json: { detail: '连接被拒绝，请核对端口' } })
    if (name === 'connect') { serial = `${payload.host}:${payload.port}`; connected = true }
    if (name === 'select') { serial = payload.serial; connected = true }
    if (name === 'disconnect') connected = false
    return route.fulfill({ json: { message: name === 'pair' ? '配对成功，请填写连接端口' : name === 'tcpip' ? '已开启5555，请点击连接' : '操作成功', device: state(), devices: devices(), selected_serial: serial } })
  })
  // Refuse any non-device write; this test never mutates a real configuration.
  await context.route('**/api/config', async (route) => route.request().method() === 'GET' ? route.continue() : route.abort('blockedbyclient'))
  await page.goto(baseURL)
  const opener = page.getByRole('button', { name: '无线连接与设备管理' })
  await opener.click()
  const dialog = page.getByRole('dialog', { name: '无线连接手机' })
  await dialog.waitFor()
  const host = dialog.getByRole('textbox', { name: '手机 IP 地址' })
  assert.equal(await host.inputValue(), '10.0.35.91')
  await dialog.getByText('设备列表已刷新。', { exact: true }).waitFor()
  await dialog.getByRole('textbox', { name: '连接端口' }).fill('1234')
  await dialog.getByRole('button', { name: '连接设备', exact: true }).click()
  await dialog.getByRole('alert').filter({ hasText: '连接被拒绝' }).waitFor()
  await dialog.getByRole('textbox', { name: '连接端口' }).fill('5555')
  await dialog.getByRole('button', { name: '连接设备', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('.device-control strong')?.textContent === '无线 ADB 已连接')
  await dialog.getByRole('tab', { name: '配对', exact: true }).click()
  await dialog.getByRole('textbox', { name: '配对端口' }).fill('37001')
  await dialog.locator('input[name=code]').fill('123456')
  await dialog.getByRole('button', { name: '配对设备', exact: true }).click()
  await dialog.getByRole('status').filter({ hasText: '配对成功' }).waitFor()
  assert.equal(await dialog.locator('input[name=code]').inputValue(), '')
  assert.equal(await page.evaluate(() => JSON.stringify(localStorage).includes('123456')), false)
  await dialog.getByRole('tab', { name: '连接', exact: true }).click()
  await dialog.getByRole('button', { name: '使用设备 usb-test', exact: true }).click()
  await dialog.getByText('只有无线调试开关？先通过 USB 启用', { exact: true }).click()
  await dialog.getByRole('button', { name: '通过 USB 开启无线 ADB', exact: true }).click()
  await dialog.getByRole('status').filter({ hasText: '已开启5555' }).waitFor()
  const connectCount = calls.filter((call) => call.name === 'connect').length
  assert.equal(connectCount, 2, 'USB enabling must not silently connect')
  await dialog.getByRole('button', { name: '连接设备', exact: true }).click()
  await dialog.getByRole('button', { name: '断开设备 10.0.35.91:5555', exact: true }).click()
  await dialog.getByText('未连接', { exact: true }).waitFor()
  await page.screenshot({ path: `${output}/wireless-device-panel.png`, fullPage: true })
  await page.keyboard.press('Escape')
  await dialog.waitFor({ state: 'detached' })
  assert.equal(await opener.evaluate((element) => element === document.activeElement), true)
  assert.deepEqual(errors, [])
  console.log(JSON.stringify({ wireless_acceptance: 'ok', connectAttempts: connectCount, pair: calls.some((call) => call.name === 'pair'), usbEnable: calls.some((call) => call.name === 'tcpip'), disconnected: calls.some((call) => call.name === 'disconnect'), errors }))
  await context.close()
} finally { await browser.close() }
