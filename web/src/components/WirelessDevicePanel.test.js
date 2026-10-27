import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import WirelessDevicePanel from './WirelessDevicePanel.vue'
import { useDeviceStore } from '../stores/deviceStore.js'
import { useRunStore } from '../stores/runStore.js'
import { useUiStore } from '../stores/uiStore.js'
import { connectDevice, disconnectDevice, enableWirelessAdb, fetchDevices, pairDevice, selectDevice } from '../api/device.js'

vi.mock('../api/device.js', () => ({
  fetchDeviceState: vi.fn(), fetchDevices: vi.fn(), connectDevice: vi.fn(), pairDevice: vi.fn(),
  selectDevice: vi.fn(), disconnectDevice: vi.fn(), enableWirelessAdb: vi.fn(),
}))
const KEY = 'wireless-device-target'
const targets = [
  { serial: 'usb-phone', state: 'device', transport: 'usb', model: 'Phone' },
  { serial: '10.0.35.91:5555', state: 'device', transport: 'wireless' },
  { serial: '10.0.35.92:4444', state: 'offline', transport: 'wireless' },
]
const state = { connected: true, state: 'device', serial: targets[1].serial, transport: 'wireless' }
const connected = { message: '连接成功', device: state, devices: targets, selected_serial: targets[1].serial }
let wrappers = []
beforeEach(() => {
  setActivePinia(createPinia())
  vi.resetAllMocks()
  localStorage.clear()
  fetchDevices.mockResolvedValue({ devices: targets, selected_serial: 'usb-phone' })
  connectDevice.mockResolvedValue(connected)
  pairDevice.mockResolvedValue({ message: '已配对', device: { connected: false, state: 'offline' }, devices: [], selected_serial: null })
  enableWirelessAdb.mockResolvedValue({ message: '已开启无线 ADB 端口 5555', device: { connected: false, state: 'offline' }, devices: [], selected_serial: null })
})
afterEach(() => { wrappers.forEach((wrapper) => wrapper.unmount()); wrappers = []; vi.restoreAllMocks(); document.body.innerHTML = '' })
async function open() {
  const wrapper = mount(WirelessDevicePanel, { attachTo: document.body })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}
function button(wrapper, text) { return wrapper.findAll('button').find((item) => item.text().includes(text)) }
async function pairTab(wrapper) { await wrapper.get('#wireless-pair-tab').trigger('click') }

it('opens as a dark dialog with default IP/port and only refreshes the device list', async () => {
  const wrapper = await open()
  expect(wrapper.get('[role="dialog"]').attributes('aria-modal')).toBe('true')
  expect(wrapper.get('[name="host"]').element.value).toBe('10.0.35.91')
  expect(wrapper.get('[name="port"]').element.value).toBe('5555')
  expect(wrapper.text()).toContain('usb-phone')
  expect(wrapper.text()).toContain('离线')
  expect(fetchDevices).toHaveBeenCalledTimes(1)
  expect(connectDevice).not.toHaveBeenCalled()
})

it('prefills the last successful connection without automatically connecting', async () => {
  localStorage.setItem(KEY, JSON.stringify({ host: '192.168.1.8', port: 37651 }))
  const wrapper = await open()
  expect(wrapper.get('[name="host"]').element.value).toBe('192.168.1.8')
  expect(wrapper.get('[name="port"]').element.value).toBe('37651')
  expect(connectDevice).not.toHaveBeenCalled()
})

it('recovers from unavailable or malformed saved storage', async () => {
  localStorage.setItem(KEY, '{bad json')
  const wrapper = await open()
  expect(wrapper.get('[name="host"]').element.value).toBe('10.0.35.91')
})

it('validates IP and port in Chinese before connecting', async () => {
  const wrapper = await open()
  await wrapper.get('[name="host"]').setValue('999.1.2.3')
  await wrapper.get('[name="port"]').setValue('65536')
  await wrapper.get('form').trigger('submit')
  expect(wrapper.text()).toContain('请输入有效的 IP 地址')
  expect(wrapper.text()).toContain('端口须为 1–65535 的整数')
  expect(wrapper.get('[name="host"]').attributes('aria-invalid')).toBe('true')
  expect(connectDevice).not.toHaveBeenCalled()
})

it('accepts IPv6 literals without treating them as hostnames', async () => {
  const wrapper = await open()
  await wrapper.get('[name="host"]').setValue('2001:db8::91')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(connectDevice).toHaveBeenCalledWith({ host: '2001:db8::91', port: 5555 })
})

it('connects once, updates state and saves only the successful host and port', async () => {
  const wrapper = await open()
  await wrapper.get('[name="host"]').setValue(' 10.0.35.91 ')
  await wrapper.get('[name="port"]').setValue('38765')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(connectDevice).toHaveBeenCalledWith({ host: '10.0.35.91', port: 38765 })
  expect(JSON.parse(localStorage.getItem(KEY))).toEqual({ host: '10.0.35.91', port: 38765 })
  expect(useDeviceStore().serial).toBe(targets[1].serial)
  expect(wrapper.get('[role="status"]').text()).toBe('连接成功')
})

it('keeps failed targets out of storage and gives wireless debugging recovery instructions', async () => {
  connectDevice.mockRejectedValueOnce(new Error('连接被拒绝'))
  const wrapper = await open()
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(localStorage.getItem(KEY)).toBe(null)
  expect(wrapper.get('[role="alert"]').text()).toContain('连接被拒绝')
  expect(wrapper.get('[role="alert"]').text()).toContain('新的配对端口和配对码')
})

it('explains different pairing/connection ports and clears the six digit password on submission', async () => {
  const wrapper = await open()
  await pairTab(wrapper)
  expect(wrapper.text()).toContain('配对端口 ≠ 连接端口')
  expect(wrapper.get('[name="port"]').element.value).toBe('')
  expect(wrapper.get('[name="code"]').attributes('type')).toBe('password')
  await wrapper.get('[name="port"]').setValue('37891')
  await wrapper.get('[name="code"]').setValue('12345a')
  await wrapper.get('form').trigger('submit')
  expect(wrapper.text()).toContain('配对码须为 6 位数字')
  expect(pairDevice).not.toHaveBeenCalled()
  await wrapper.get('[name="code"]').setValue('012345')
  await wrapper.get('form').trigger('submit')
  expect(wrapper.get('[name="code"]').element.value).toBe('')
  await flushPromises()
  expect(pairDevice).toHaveBeenCalledWith({ host: '10.0.35.91', port: 37891, code: '012345' })
  expect(connectDevice).not.toHaveBeenCalled()
  expect(useDeviceStore().connected).toBe(false)
  expect(wrapper.get('[role="status"]').text()).toBe('已配对')
  expect(localStorage.getItem(KEY)).toBe(null)
  await wrapper.get('#wireless-connect-tab').trigger('click')
  expect(wrapper.get('[name="port"]').element.value).toBe('5555')
})

it('clears pairing codes after failed submission and when changing tabs', async () => {
  pairDevice.mockRejectedValueOnce(new Error('配对码失效'))
  const wrapper = await open()
  await pairTab(wrapper)
  await wrapper.get('[name="port"]').setValue('37891')
  await wrapper.get('[name="code"]').setValue('654321')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.get('[name="code"]').element.value).toBe('')
  await wrapper.get('[name="code"]').setValue('123456')
  await wrapper.get('#wireless-connect-tab').trigger('click')
  await pairTab(wrapper)
  expect(wrapper.get('[name="code"]').element.value).toBe('')
})

it('blocks duplicate operations while a request is pending', async () => {
  let done
  connectDevice.mockReturnValueOnce(new Promise((resolve) => { done = resolve }))
  const wrapper = await open()
  await wrapper.get('form').trigger('submit')
  await wrapper.get('form').trigger('submit')
  expect(connectDevice).toHaveBeenCalledTimes(1)
  expect(wrapper.get('[type="submit"]').attributes('disabled')).toBeDefined()
  expect(button(wrapper, '刷新列表').attributes('disabled')).toBeDefined()
  done(connected)
  await flushPromises()
  expect(wrapper.get('[type="submit"]').attributes('disabled')).toBeUndefined()
})

it('selects a device and disconnects the specific wireless serial', async () => {
  selectDevice.mockResolvedValue(connected)
  disconnectDevice.mockResolvedValue({ ...connected, message: '已断开' })
  const wrapper = await open()
  await wrapper.get('[aria-label="使用设备 10.0.35.91:5555"]').trigger('click')
  await flushPromises()
  expect(selectDevice).toHaveBeenCalledWith('10.0.35.91:5555')
  await wrapper.get('[aria-label="断开设备 10.0.35.92:4444"]').trigger('click')
  await flushPromises()
  expect(disconnectDevice).toHaveBeenCalledWith('10.0.35.92:4444')
  expect(wrapper.find('[aria-label="断开设备 usb-phone"]').exists()).toBe(false)
})

it.each(['running', 'readOnly'])('allows viewing and refreshing while %s blocks all mutations', async (mode) => {
  if (mode === 'running') useRunStore().state = 'running'
  else useUiStore().readOnly = true
  const wrapper = await open()
  expect(wrapper.get('[type="submit"]').attributes('disabled')).toBeDefined()
  expect(button(wrapper, '通过 USB 开启').attributes('disabled')).toBeDefined()
  expect(wrapper.get('[aria-label="使用设备 10.0.35.91:5555"]').attributes('disabled')).toBeDefined()
  expect(wrapper.get('[aria-label="断开设备 10.0.35.91:5555"]').attributes('disabled')).toBeDefined()
  await wrapper.get('form').trigger('submit')
  expect(connectDevice).not.toHaveBeenCalled()
  await pairTab(wrapper)
  expect(wrapper.get('[name="code"]').attributes('disabled')).toBeDefined()
  expect(wrapper.get('[type="submit"]').attributes('disabled')).toBeDefined()
  await button(wrapper, '刷新列表').trigger('click')
  await flushPromises()
  expect(fetchDevices).toHaveBeenCalledTimes(2)
})

it('enables traditional ADB through USB and waits for an explicit connect', async () => {
  const wrapper = await open()
  expect(wrapper.get('summary').text()).toContain('只有无线调试开关')
  await button(wrapper, '通过 USB 开启').trigger('click')
  await flushPromises()
  expect(enableWirelessAdb).toHaveBeenCalledWith(5555)
  expect(connectDevice).not.toHaveBeenCalled()
  expect(wrapper.get('[role="status"]').text()).toContain('5555')
})

it('traps focus, emits close on Escape/cancel and restores the trigger on unmount', async () => {
  const trigger = document.createElement('button')
  document.body.appendChild(trigger)
  trigger.focus()
  const wrapper = await open()
  const first = wrapper.get('[aria-label="关闭无线设备面板"]').element
  const last = button(wrapper, '取消').element
  last.focus()
  await wrapper.get('[role="dialog"]').trigger('keydown', { key: 'Tab' })
  expect(document.activeElement).toBe(first)
  await wrapper.get('[role="dialog"]').trigger('keydown', { key: 'Tab', shiftKey: true })
  expect(document.activeElement).toBe(last)
  trigger.focus()
  expect(document.activeElement).toBe(first)
  await wrapper.get('[role="dialog"]').trigger('keydown', { key: 'Escape' })
  expect(wrapper.emitted('close')).toHaveLength(1)
  await button(wrapper, '取消').trigger('click')
  expect(wrapper.emitted('close')).toHaveLength(2)
  wrapper.unmount()
  wrappers = []
  expect(document.activeElement).toBe(trigger)
})
