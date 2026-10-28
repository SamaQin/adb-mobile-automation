<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { AlertTriangle, RefreshCw, WifiOff, X } from 'lucide-vue-next'
import DeviceMonitor from './components/DeviceMonitor.vue'
import WirelessDevicePanel from './components/WirelessDevicePanel.vue'
import AppDialog from './components/AppDialog.vue'
import WorkspaceHelp from './components/WorkspaceHelp.vue'
import WorkspaceStatus from './components/WorkspaceStatus.vue'
import FlowCanvas from './components/FlowCanvas.vue'
import LogPanel from './components/editors/LogPanel.vue'
import PresetToolbar from './components/editors/PresetToolbar.vue'
import ScreenshotEditor from './components/editors/ScreenshotEditor.vue'
import TemplateManager from './components/editors/TemplateManager.vue'
import NodePalette from './components/panes/NodePalette.vue'
import PropertiesPanel from './components/panes/PropertiesPanel.vue'
import { useConfigStore } from './stores/configStore.js'
import { useDeviceStore } from './stores/deviceStore.js'
import { useHistoryStore } from './stores/historyStore.js'
import { useRunStore } from './stores/runStore.js'
import { useUiStore } from './stores/uiStore.js'

const configStore = useConfigStore()
const deviceStore = useDeviceStore()
const historyStore = useHistoryStore()
const runStore = useRunStore()
const uiStore = useUiStore()
const flowCanvas = ref(null)
const ready = computed(() => Boolean(configStore.config && configStore.selectedPreset))
let faviconTimer = null
let faviconLink = null
let originalFavicon = ''
let showFailureFavicon = false

function failedNodesPresent(nodeStates) {
  return Object.values(nodeStates).some((node) => node?.state === 'failed')
}

function setFailureFavicon(enabled) {
  if (!faviconLink) {
    faviconLink = document.querySelector('link[rel~="icon"]')
    if (!faviconLink) {
      faviconLink = document.createElement('link')
      faviconLink.rel = 'icon'
      faviconLink.href = createDefaultFavicon()
      document.head.appendChild(faviconLink)
    }
    originalFavicon = faviconLink.href
  }

  if (enabled) {
    showFailureFavicon = !showFailureFavicon
    faviconLink.href = showFailureFavicon ? createFailureFavicon() : originalFavicon
  } else {
    faviconLink.href = originalFavicon
    showFailureFavicon = false
  }
}

function createDefaultFavicon() {
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#0ea5e9"/><path d="M18 18h28v6H24v9h20v6H24v9h22v6H18z" fill="#fff"/></svg>'
  return `data:image/svg+xml,${encodeURIComponent(svg)}`
}

function createFailureFavicon() {
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#ef4444"/><path d="M32 12 56 52H8z" fill="#fff"/><path d="M32 25v13m0 6v1" stroke="#ef4444" stroke-width="5" stroke-linecap="round"/></svg>'
  return `data:image/svg+xml,${encodeURIComponent(svg)}`
}

function stopFaviconAlert() {
  if (faviconTimer) clearInterval(faviconTimer)
  faviconTimer = null
  setFailureFavicon(false)
}

watch(() => failedNodesPresent(runStore.nodeStates), (hasFailure) => {
  if (hasFailure) {
    if (!faviconTimer) faviconTimer = setInterval(() => setFailureFavicon(true), 600)
  } else {
    stopFaviconAlert()
  }
}, { immediate: true })

function handleVisibilityChange() {
  if (document.visibilityState === 'visible' && failedNodesPresent(runStore.nodeStates)) stopFaviconAlert()
}

async function initialize() {
  await configStore.load()
  await Promise.allSettled([deviceStore.check(), runStore.refreshStatus()])
  runStore.connect(() => {
    if (!configStore.dirty) configStore.load().catch(() => {})
  })
}

function globalKeys(event) {
  const target = event.target
  const ctrl = event.ctrlKey || event.metaKey
  if (ctrl && event.key.toLowerCase() === 's') {
    event.preventDefault()
    if (uiStore.dialog || uiStore.helpOpen || uiStore.screenshotRequest || uiStore.templateDrawerOpen || uiStore.wirelessDeviceOpen || uiStore.recordingOpen || runStore.running || uiStore.readOnly || configStore.saving) return
    target?.blur?.()
    configStore.save().then(() => uiStore.notify('配置已保存', 'success')).catch((error) => uiStore.notify(error.message, 'error'))
    return
  }
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(target?.tagName) || target?.isContentEditable) return
  if (uiStore.dialog || uiStore.helpOpen || uiStore.screenshotRequest || uiStore.templateDrawerOpen || uiStore.wirelessDeviceOpen || uiStore.recordingOpen) return
  if (event.key === '?' || event.key === 'F1') {
    event.preventDefault()
    uiStore.helpOpen = true
    return
  }
  if (ctrl && ['z', 'y', 's'].includes(event.key.toLowerCase()) && (runStore.running || uiStore.readOnly || configStore.saving)) {
    event.preventDefault()
    return
  }
  if (ctrl && event.key.toLowerCase() === 'z') {
    event.preventDefault()
    const snapshot = event.shiftKey ? historyStore.redo(configStore.snapshot()) : historyStore.undo(configStore.snapshot())
    if (snapshot) { configStore.replaceFromHistory(snapshot); uiStore.clearSelection() }
  } else if (ctrl && event.key.toLowerCase() === 'y') {
    event.preventDefault()
    const snapshot = historyStore.redo(configStore.snapshot())
    if (snapshot) { configStore.replaceFromHistory(snapshot); uiStore.clearSelection() }
  }
}

function beforeUnload(event) {
  if (!configStore.dirty) return
  event.preventDefault()
  event.returnValue = ''
}

onMounted(() => {
  initialize().catch(() => {})
  window.addEventListener('keydown', globalKeys)
  window.addEventListener('beforeunload', beforeUnload)
  document.addEventListener('visibilitychange', handleVisibilityChange)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', globalKeys)
  window.removeEventListener('beforeunload', beforeUnload)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  stopFaviconAlert()
  runStore.socket?.close()
})
</script>

<template>
  <div class="app-shell">
    <div v-if="!ready && configStore.loading" class="boot-screen"><RefreshCw :size="28" class="spin" /><strong>正在加载工作台</strong></div>
    <div v-else-if="!ready" class="boot-screen error"><WifiOff :size="30" /><strong>无法加载配置</strong><span>{{ configStore.error || '后端服务未就绪' }}</span><button class="primary" @click="initialize"><RefreshCw :size="15" />重试</button></div>
    <template v-else>
      <PresetToolbar @auto-layout="flowCanvas?.autoLayout()" />
      <WorkspaceStatus @focus-node="flowCanvas?.focusNode($event)" />
      <div class="workbench-grid" :class="{ 'logs-collapsed': uiStore.logCollapsed, 'palette-collapsed': uiStore.paletteCollapsed, 'properties-collapsed': uiStore.propertiesCollapsed }">
        <NodePalette @add="flowCanvas?.addStep($event)" />
        <FlowCanvas ref="flowCanvas" />
        <PropertiesPanel :edges="flowCanvas?.edges || []" />
        <LogPanel @focus-node="flowCanvas?.focusNode($event)" />
      </div>
    </template>

    <DeviceMonitor v-if="ready && uiStore.deviceMonitorOpen" @hide="uiStore.deviceMonitorOpen = false" />
    <WirelessDevicePanel v-if="ready && uiStore.wirelessDeviceOpen" @close="uiStore.wirelessDeviceOpen = false" />
    <TemplateManager v-if="uiStore.templateDrawerOpen" @close="uiStore.templateDrawerOpen = false" />
    <ScreenshotEditor v-if="uiStore.screenshotRequest" :request="uiStore.screenshotRequest" @close="uiStore.closeScreenshot($event)" />

    <WorkspaceHelp v-if="uiStore.helpOpen" />
    <AppDialog />
    <div v-if="uiStore.toast" class="toast" :class="uiStore.toast.tone" role="status"><AlertTriangle v-if="uiStore.toast.tone === 'error'" :size="16" /><span>{{ uiStore.toast.message }}</span><button v-if="uiStore.toast.action" class="toast-action" @click="const action = uiStore.toast.action; uiStore.toast = null; action.run()">{{ uiStore.toast.action.label }}</button><button title="关闭通知" @click="uiStore.toast = null"><X :size="14" /></button></div>
  </div>
</template>
