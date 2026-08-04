<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { AlertTriangle, RefreshCw, WifiOff, X } from 'lucide-vue-next'
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

async function initialize() {
  await configStore.load()
  await Promise.allSettled([deviceStore.check(), runStore.refreshStatus()])
  runStore.connect(() => {
    if (!configStore.dirty) configStore.load().catch(() => {})
  })
}

function globalKeys(event) {
  const target = event.target
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(target?.tagName) || target?.isContentEditable) return
  const ctrl = event.ctrlKey || event.metaKey
  if (ctrl && event.key.toLowerCase() === 'z') {
    event.preventDefault()
    const snapshot = event.shiftKey ? historyStore.redo(configStore.snapshot()) : historyStore.undo(configStore.snapshot())
    if (snapshot) configStore.replaceFromHistory(snapshot)
  } else if (ctrl && event.key.toLowerCase() === 'y') {
    event.preventDefault()
    const snapshot = historyStore.redo(configStore.snapshot())
    if (snapshot) configStore.replaceFromHistory(snapshot)
  } else if (ctrl && event.key.toLowerCase() === 's') {
    event.preventDefault()
    if (!runStore.running && !uiStore.readOnly) configStore.save().catch((error) => uiStore.notify(error.message, 'error'))
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
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', globalKeys)
  window.removeEventListener('beforeunload', beforeUnload)
  runStore.socket?.close()
})
</script>

<template>
  <div class="app-shell">
    <div v-if="!ready && configStore.loading" class="boot-screen"><RefreshCw :size="28" class="spin" /><strong>正在加载工作台</strong></div>
    <div v-else-if="!ready" class="boot-screen error"><WifiOff :size="30" /><strong>无法加载配置</strong><span>{{ configStore.error || '后端服务未就绪' }}</span><button class="primary" @click="initialize"><RefreshCw :size="15" />重试</button></div>
    <template v-else>
      <PresetToolbar @auto-layout="flowCanvas?.autoLayout()" />
      <div class="workbench-grid" :class="{ 'logs-collapsed': uiStore.logCollapsed, 'palette-collapsed': uiStore.paletteCollapsed, 'properties-collapsed': uiStore.propertiesCollapsed }">
        <NodePalette @add="flowCanvas?.addStep($event)" />
        <FlowCanvas ref="flowCanvas" />
        <PropertiesPanel :edges="flowCanvas?.edges || []" />
        <LogPanel @focus-node="flowCanvas?.focusNode($event)" />
      </div>
    </template>

    <TemplateManager v-if="uiStore.templateDrawerOpen" @close="uiStore.templateDrawerOpen = false" />
    <ScreenshotEditor v-if="uiStore.screenshotRequest" :request="uiStore.screenshotRequest" @close="uiStore.closeScreenshot($event)" />

    <div v-if="uiStore.toast" class="toast" :class="uiStore.toast.tone" role="status"><AlertTriangle v-if="uiStore.toast.tone === 'error'" :size="16" /><span>{{ uiStore.toast.message }}</span><button title="关闭通知" @click="uiStore.toast = null"><X :size="14" /></button></div>
  </div>
</template>
