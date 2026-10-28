<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RefreshCw, Wifi, X } from 'lucide-vue-next'
import { useDeviceStore } from '../stores/deviceStore.js'
import { useRunStore } from '../stores/runStore.js'
import { useUiStore } from '../stores/uiStore.js'

const emit = defineEmits(['close'])
const device = useDeviceStore()
const run = useRunStore()
const ui = useUiStore()
const STORAGE_KEY = 'wireless-device-target'
function savedTarget() {
  try { return JSON.parse(window.localStorage.getItem(STORAGE_KEY)) || {} } catch { return {} }
}
const saved = savedTarget()
const host = ref(typeof saved.host === 'string' ? saved.host : '10.0.35.91')
const connectPort = ref(String(saved.port || 5555))
const pairPort = ref('')
const code = ref('')
const tab = ref('connect')
const panel = ref(null)
const feedback = ref('')
const feedbackError = ref(false)
const fieldErrors = ref({})
const localBusy = ref(false)
const previousFocus = document.activeElement
const busy = computed(() => localBusy.value || device.operationBusy || device.refreshing)
const locked = computed(() => run.running || run.preparing || ui.readOnly)
const lockReason = computed(() => run.running ? '运行中可查看和刷新设备，停止后可连接、配对、切换或断开。' : run.preparing ? '正在准备运行，请稍候再操作设备。' : ui.readOnly ? '只读模式：可查看和刷新设备，不能连接、配对、切换或断开。' : '')
const status = computed(() => device.connected ? '已连接' : device.state === 'unauthorized' ? '未授权' : device.state === 'offline' ? '离线' : device.state === 'error' ? '检测失败' : '未连接')
const currentTarget = computed(() => device.serial || device.selectedSerial || '尚未选择设备')
function stateLabel(state) {
  return ({ device: '已连接', offline: '离线', unauthorized: '未授权' })[state] || state || '状态未知'
}
function wireless(target) {
  return ['wireless', 'tcp', 'tcpip', 'wifi'].includes(target.transport) || /^.+:\d+$/.test(target.serial || '') || (target.serial || '').includes('._adb-tls-connect._tcp')
}
function validate() {
  const errors = {}
  const address = host.value.trim().replace(/^\[|\]$/g, '')
  const parts = address.split('.')
  const ipv4 = parts.length === 4 && parts.every((part) => /^(0|[1-9]\d{0,2})$/.test(part) && Number(part) <= 255)
  let ipv6 = false
  if (address.includes(':') && /^[0-9a-f:.]+$/i.test(address)) {
    try { ipv6 = new URL(`http://[${address}]/`).hostname.startsWith('[') } catch { /* Invalid IPv6 literal. */ }
  }
  if (!ipv4 && !ipv6) errors.host = '请输入有效的 IP 地址，例如 10.0.35.91。'
  const port = tab.value === 'pair' ? pairPort.value.trim() : connectPort.value.trim()
  if (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535) errors.port = '端口须为 1–65535 的整数，请填写手机显示的端口。'
  if (tab.value === 'pair' && !/^\d{6}$/.test(code.value)) errors.code = '配对码须为 6 位数字。'
  fieldErrors.value = errors
  return Object.keys(errors).length === 0
}
function close() { code.value = ''; emit('close') }
async function perform(action, success) {
  if (busy.value) return
  localBusy.value = true
  feedback.value = ''
  feedbackError.value = false
  try {
    const result = await action()
    feedback.value = result?.message || success
  } catch (error) {
    feedbackError.value = true
    feedback.value = error.message || '设备操作失败，请检查手机的无线调试设置后重试。'
  } finally { localBusy.value = false }
}
async function submit() {
  if (locked.value || busy.value || !validate()) return
  const target = { host: host.value.trim(), port: Number(tab.value === 'pair' ? pairPort.value : connectPort.value) }
  if (tab.value === 'pair') {
    const pairingCode = code.value
    code.value = ''
    await perform(() => device.pair({ ...target, code: pairingCode }), '已配对。请切换到“连接”，填写无线调试主页的连接端口。')
  } else {
    await perform(async () => {
      const result = await device.connect(target)
      try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(target)) } catch { /* Storage may be unavailable. */ }
      return result
    }, '无线设备已连接。')
  }
}
function refresh() {
  return perform(async () => { await device.refreshDevices(); return null }, '设备列表已刷新。')
}
function enableWireless() {
  if (locked.value) return
  return perform(() => device.enableWireless(5555), '已通过 USB 开启无线 ADB（端口 5555）。请填写手机 IP，再点击“连接设备”。')
}
function select(serial) {
  if (locked.value) return
  return perform(() => device.select(serial), '已切换当前设备。')
}
function disconnect(serial) {
  if (locked.value) return
  return perform(() => device.disconnect(serial), '已断开无线设备。')
}
function focusable() {
  return [...(panel.value?.querySelectorAll('button:not(:disabled), input:not(:disabled), summary, [tabindex="0"]') || [])]
}
function keys(event) {
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); return }
  if (event.key !== 'Tab') return
  const elements = focusable()
  const first = elements[0], last = elements.at(-1)
  if (!elements.length) { event.preventDefault(); panel.value?.focus() }
  else if (event.shiftKey && (document.activeElement === first || !panel.value.contains(document.activeElement))) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && (document.activeElement === last || !panel.value.contains(document.activeElement))) { event.preventDefault(); first.focus() }
}
function containFocus(event) {
  if (panel.value && !panel.value.contains(event.target)) focusable()[0]?.focus()
}
watch(tab, () => { code.value = ''; fieldErrors.value = {}; feedback.value = '' })
onMounted(async () => {
  document.addEventListener('keydown', keys, true)
  document.addEventListener('focusin', containFocus)
  await nextTick()
  panel.value?.querySelector('input')?.focus()
  refresh()
})
onBeforeUnmount(() => {
  code.value = ''
  document.removeEventListener('keydown', keys, true)
  document.removeEventListener('focusin', containFocus)
  if (previousFocus?.isConnected) previousFocus.focus()
})
</script>

<template>
  <div class="wireless-backdrop">
    <section ref="panel" class="wireless-panel" role="dialog" aria-modal="true" aria-labelledby="wireless-title" aria-describedby="wireless-description" tabindex="-1" :aria-busy="busy">
      <header>
        <div class="heading"><Wifi :size="20" /><div><h2 id="wireless-title">无线连接手机</h2><p id="wireless-description">手机与电脑需处于同一局域网</p></div></div>
        <button type="button" class="icon-button" aria-label="关闭无线设备面板" @click="close"><X :size="18" /></button>
      </header>
      <div class="current-device"><span class="status" :class="{ connected: device.connected }">{{ status }}</span><span>当前设备：<strong>{{ currentTarget }}</strong></span><small v-if="device.transport">{{ device.transport === 'wireless' ? '无线' : 'USB' }}</small></div>
      <p v-if="device.error" class="device-error">{{ device.error }}</p>
      <p v-if="lockReason" class="lock-note">{{ lockReason }}</p>
      <div class="tabs" role="tablist" aria-label="无线设备操作">
        <button id="wireless-connect-tab" type="button" role="tab" :aria-selected="tab === 'connect'" aria-controls="wireless-form" :disabled="busy" @click="tab = 'connect'">连接</button>
        <button id="wireless-pair-tab" type="button" role="tab" :aria-selected="tab === 'pair'" aria-controls="wireless-form" :disabled="busy" @click="tab = 'pair'">配对</button>
      </div>
      <form id="wireless-form" role="tabpanel" :aria-labelledby="tab === 'pair' ? 'wireless-pair-tab' : 'wireless-connect-tab'" novalidate @submit.prevent="submit">
        <p v-if="tab === 'connect'" class="help">开启手机「开发者选项 → 无线调试」，填写无线调试主页显示的 IP 地址和连接端口。有“使用配对码配对设备”入口时，首次连接请先配对；只有开关时可展开下方 USB 启用说明。</p>
        <p v-else class="help">Android 11 及以上：打开「无线调试 → 使用配对码配对设备」，填写弹窗中的随机配对端口及 6 位配对码。<strong>配对端口 ≠ 连接端口</strong>；配对成功后仍需切回“连接”，填写无线调试主页的连接端口。</p>
        <div class="target-fields">
          <label class="address-field"><span>手机 IP 地址</span><input v-model="host" name="host" inputmode="decimal" autocomplete="off" placeholder="10.0.35.91" :disabled="locked || busy" :aria-invalid="!!fieldErrors.host" :aria-describedby="fieldErrors.host ? 'wireless-host-error' : undefined" /><small v-if="fieldErrors.host" id="wireless-host-error" class="field-error">{{ fieldErrors.host }}</small></label>
          <label><span>{{ tab === 'pair' ? '配对端口' : '连接端口' }}</span><input v-if="tab === 'pair'" v-model="pairPort" name="port" inputmode="numeric" autocomplete="off" placeholder="手机弹窗中的端口" :disabled="locked || busy" :aria-invalid="!!fieldErrors.port" :aria-describedby="fieldErrors.port ? 'wireless-port-error' : undefined" /><input v-else v-model="connectPort" name="port" inputmode="numeric" autocomplete="off" :disabled="locked || busy" :aria-invalid="!!fieldErrors.port" :aria-describedby="fieldErrors.port ? 'wireless-port-error' : undefined" /><small v-if="fieldErrors.port" id="wireless-port-error" class="field-error">{{ fieldErrors.port }}</small></label>
        </div>
        <label v-if="tab === 'pair'" class="code-field"><span>6 位配对码</span><input v-model="code" name="code" type="password" inputmode="numeric" autocomplete="off" maxlength="6" placeholder="仅用于本次配对" :disabled="locked || busy" :aria-invalid="!!fieldErrors.code" :aria-describedby="fieldErrors.code ? 'wireless-code-error' : undefined" /><small v-if="fieldErrors.code" id="wireless-code-error" class="field-error">{{ fieldErrors.code }}</small></label>
        <div class="submit-row"><small>仅记住成功连接的 IP 和端口，下次打开不会自动连接。</small><button type="submit" class="primary" :disabled="locked || busy">{{ device.operationBusy ? '操作中…' : tab === 'pair' ? '配对设备' : '连接设备' }}</button></div>
      </form>
      <details v-if="tab === 'connect'" class="usb-help">
        <summary>只有无线调试开关？先通过 USB 启用</summary>
        <p>部分手机没有配对码页面，或连接 5555 提示拒绝连接。请先用 USB 连接手机，在手机上允许 USB 调试授权，再点击下方按钮开启传统无线 ADB（5555）。成功后填写上方手机 IP，手动点击“连接设备”；连接成功后可拔下 USB。</p>
        <button type="button" :disabled="locked || busy" @click="enableWireless">通过 USB 开启无线 ADB</button>
      </details>
      <p v-if="feedback" class="feedback" :class="{ failure: feedbackError }" :role="feedbackError ? 'alert' : 'status'">{{ feedback }}<span v-if="feedbackError"> 请核对 IP 和端口。只有无线调试开关时，可先通过 USB 授权并启用；有配对页面时请使用新的配对端口和配对码。</span></p>
      <section class="device-list" aria-labelledby="wireless-devices-title">
        <div class="list-heading"><h3 id="wireless-devices-title">已发现的设备</h3><button type="button" :disabled="busy" @click="refresh"><RefreshCw :size="13" />{{ device.refreshing ? '刷新中…' : '刷新列表' }}</button></div>
        <p v-if="!device.devices.length" class="empty">{{ device.refreshing ? '正在读取设备列表…' : '暂无设备。开启无线调试后，填写手机显示的 IP 和端口进行连接。' }}</p>
        <ul v-else>
          <li v-for="target in device.devices" :key="target.serial">
            <div class="device-info"><strong>{{ target.serial }}</strong><small>{{ stateLabel(target.state || target.status) }} · {{ wireless(target) ? '无线' : 'USB' }}<template v-if="target.model"> · {{ target.model }}</template></small></div>
            <span v-if="target.serial === device.selectedSerial" class="selected">当前使用</span>
            <button v-else type="button" :disabled="locked || busy || (target.state || target.status) !== 'device'" :aria-label="`使用设备 ${target.serial}`" @click="select(target.serial)">使用</button>
            <button v-if="wireless(target)" type="button" class="disconnect" :disabled="locked || busy" :aria-label="`断开设备 ${target.serial}`" @click="disconnect(target.serial)">断开</button>
          </li>
        </ul>
      </section>
      <footer><button type="button" @click="close">取消</button></footer>
    </section>
  </div>
</template>

<style scoped>
.wireless-backdrop { position: fixed; inset: 0; z-index: 850; display: grid; place-items: center; padding: 20px; background: rgba(0, 0, 0, .65); backdrop-filter: blur(3px); }
.wireless-panel { width: min(620px, 100%); max-height: calc(100dvh - 40px); overflow: auto; padding: 22px; border: 1px solid #304056; border-radius: 14px; color: var(--text, #e2eaf5); background: #141f2d; box-shadow: 0 24px 80px #0008; }
header, .heading, .current-device, .list-heading, .submit-row, li, footer { display: flex; align-items: center; gap: 10px; }
header, .list-heading { justify-content: space-between; }
.heading { color: #65b7ff; }
h2 { margin: 0; font-size: 18px; color: var(--text, #e2eaf5); }
header p { margin: 5px 0 0; font-size: 12px; color: var(--muted, #91a1b5); }
.current-device { flex-wrap: wrap; padding: 14px 0; font-size: 12px; overflow-wrap: anywhere; }
.status, .selected { color: #a7b7cb; font-size: 11px; border-radius: 5px; padding: 3px 6px; background: #263447; white-space: nowrap; }
.status.connected, .selected { color: #7bddb0; background: #173c34; }
.current-device small, .help, .submit-row small, .empty, .device-info small { color: var(--muted, #91a1b5); }
.tabs { display: flex; gap: 6px; border-bottom: 1px solid #304056; padding-bottom: 8px; }
.tabs button { min-width: 82px; }
.tabs [aria-selected="true"] { color: #8ccaff; background: #1b3a58; border-color: #38648b; }
.help { margin: 14px 0; font-size: 12px; line-height: 1.8; }
.help strong { color: #f0c684; }
.target-fields { display: grid; grid-template-columns: 1.5fr 1fr; gap: 12px; }
label { display: flex; flex-direction: column; gap: 7px; font-size: 12px; }
input { width: 100%; min-width: 0; box-sizing: border-box; }
input[aria-invalid="true"] { border-color: #f08888; }
.code-field { margin-top: 12px; }
.code-field input { max-width: 240px; letter-spacing: .16em; }
.field-error, .device-error { color: #ffaaaa; line-height: 1.6; }
.submit-row { justify-content: space-between; margin-top: 16px; }
.submit-row small { max-width: 330px; font-size: 11px; line-height: 1.6; }
.submit-row button { white-space: nowrap; }
.lock-note, .feedback { padding: 10px 12px; border-radius: 6px; background: #23384c; color: #b2d6f4; font-size: 12px; line-height: 1.7; }
.feedback { color: #8be4bd; background: #183a33; }
.feedback.failure { color: #ffc0b6; background: #462b2e; }
.usb-help { margin-top: 16px; padding: 10px 12px; background: #1c2b3d; border: 1px solid #304056; border-radius: 6px; font-size: 12px; }
.usb-help summary { cursor: pointer; color: #b8d9f5; }
.usb-help p { color: var(--muted, #91a1b5); line-height: 1.8; }
.device-list { margin-top: 20px; border-top: 1px solid #304056; padding-top: 15px; }
h3 { margin: 0; font-size: 13px; }
ul { list-style: none; padding: 0; margin: 8px 0 0; max-height: 230px; overflow: auto; }
li { padding: 11px 0; border-bottom: 1px solid #28374b; }
.device-info { display: flex; flex: 1; min-width: 0; flex-direction: column; gap: 5px; font-size: 12px; overflow-wrap: anywhere; }
.device-info small { font-size: 11px; }
.empty { font-size: 12px; line-height: 1.7; }
.disconnect { color: #f0af9d; }
footer { justify-content: flex-end; margin-top: 18px; }
footer button { min-width: 74px; }
button:focus-visible, input:focus-visible { outline: 2px solid #7cc5ff; outline-offset: 3px; }
@media (max-width: 520px) { .wireless-panel { padding: 16px; } .target-fields { grid-template-columns: 1fr; } .submit-row { align-items: flex-end; } li { flex-wrap: wrap; } .device-info { flex-basis: 100%; } }
</style>
