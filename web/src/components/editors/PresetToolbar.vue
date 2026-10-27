<script setup>
import { computed, ref } from 'vue'
import {
  ArchiveRestore,
  CheckCircle2,
  Copy,
  Download,
  FolderInput,
  Gauge,
  LayoutTemplate,
  MonitorCheck,
  Pencil,
  Play,
  Redo2,
  Save,
  Square,
  Trash2,
  Undo2,
} from 'lucide-vue-next'
import { downloadBlob } from '../../api/client.js'
import { exportPresetArchive, importPresetArchive } from '../../api/archive.js'
import { useConfigStore } from '../../stores/configStore.js'
import { useDeviceStore } from '../../stores/deviceStore.js'
import { useHistoryStore } from '../../stores/historyStore.js'
import { useRunStore } from '../../stores/runStore.js'
import { useUiStore } from '../../stores/uiStore.js'

const emit = defineEmits(['auto-layout', 'layout-reorder', 'reset-layout', 'canvas-export', 'canvas-import'])
const configStore = useConfigStore()
const deviceStore = useDeviceStore()
const historyStore = useHistoryStore()
const runStore = useRunStore()
const uiStore = useUiStore()
const archiveInput = ref(null)
const locked = computed(() => uiStore.readOnly || runStore.running || configStore.saving)

function hasEnabledStep(steps) {
  for (const step of steps || []) {
    if (step.enabled) return true
    for (const branch of Object.values(step.params?.branches || {})) {
      if (hasEnabledStep(branch)) return true
    }
  }
  return false
}

async function safe(action) {
  try { await action() } catch (error) { uiStore.notify(error.message, 'error') }
}

async function switchPreset(event) {
  configStore.selectPreset(event.target.value)
  await safe(() => configStore.save())
}

function newPreset() {
  const name = window.prompt('新预设名称')
  if (name != null) safe(async () => { configStore.addPreset(name); await configStore.save() })
}

function renamePreset() {
  const name = window.prompt('预设名称', configStore.selectedPreset.name)
  if (name != null) safe(() => configStore.renamePreset(configStore.selectedPreset.id, name))
}

async function deletePreset() {
  const references = await configStore.referencesForPreset(configStore.selectedPreset.id)
  const referenceText = references.length
    ? `\n\n以下步骤正在引用它：\n${references.map((item) => `${item.preset_name || item.preset} / ${item.step_name || item.step}`).join('\n')}`
    : ''
  if (window.confirm(`删除预设“${configStore.selectedPreset.name}”？${referenceText}`)) configStore.deletePreset(configStore.selectedPreset.id)
}

function undo() {
  const snapshot = historyStore.undo(configStore.snapshot())
  if (snapshot) configStore.replaceFromHistory(snapshot)
}

function redo() {
  const snapshot = historyStore.redo(configStore.snapshot())
  if (snapshot) configStore.replaceFromHistory(snapshot)
}

async function save(title = '配置已保存') {
  await deviceStore.check().catch(() => false)
  if (deviceStore.resolution) configStore.applyScreenResolution(deviceStore.resolution)
  await configStore.save()
  uiStore.notify(title, 'success')
}

async function run() {
  if (runStore.running) return safe(() => runStore.stop())
  if (configStore.dirty) await save('未保存的修改已自动保存')
  const connected = await deviceStore.check()
  if (!connected) throw new Error(deviceStore.error || '未连接 ADB 设备')
  if (configStore.selectedPreset.loop_count === 0 && !hasEnabledStep(configStore.selectedPreset.steps)) throw new Error('无限循环预设至少需要一个启用步骤')
  uiStore.clearSelection()
  await runStore.start(configStore.selectedPreset.id)
}

async function exportArchive() {
  const blob = await exportPresetArchive(configStore.selectedPreset.id)
  const clean = configStore.selectedPreset.name.replace(/[<>:"/\\|?*]/g, '_')
  downloadBlob(blob, `${clean}.adb-preset.zip`)
}

async function importArchive(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  const result = await importPresetArchive(file)
  if (result?.presets) configStore.config = result
  else await configStore.load()
  emit('auto-layout')
  uiStore.notify('预设包已导入', 'success')
}

function changeLoop(event) {
  safe(() => configStore.setLoopCount(event.target.value))
}

function changeAcceleration(event) {
  safe(() => configStore.setAcceleration(event.target.value))
}
</script>

<template>
  <header class="topbar panel">
    <div class="device-control">
      <span class="device-dot" :class="{ connected: deviceStore.connected }" />
      <span><strong>{{ deviceStore.connected ? 'ADB 已连接' : 'ADB 未连接' }}</strong><small v-if="deviceStore.resolution">{{ deviceStore.resolution.width }}×{{ deviceStore.resolution.height }}</small><small v-else>{{ deviceStore.state }}</small></span>
      <button class="icon-button" title="检查设备" :disabled="deviceStore.checking" @click="safe(() => deviceStore.check())"><MonitorCheck :size="16" /></button>
    </div>

    <div class="toolbar-separator" />
    <label class="preset-select"><span>预设</span><select :value="configStore.selectedPreset?.id" :disabled="runStore.running || configStore.saving" @change="switchPreset"><option v-for="preset in configStore.presets" :key="preset.id" :value="preset.id">{{ preset.name }}</option></select></label>
    <div class="button-cluster">
      <button title="新建预设" :disabled="locked" @click="newPreset"><FolderInput :size="15" /></button>
      <button title="复制预设" :disabled="locked" @click="safe(() => configStore.duplicatePreset(configStore.selectedPreset.id))"><Copy :size="15" /></button>
      <button title="重命名预设" :disabled="locked" @click="renamePreset"><Pencil :size="15" /></button>
      <button title="删除预设" class="danger" :disabled="locked" @click="safe(deletePreset)"><Trash2 :size="15" /></button>
    </div>

    <label class="compact-control" title="0 表示无限循环"><span>循环</span><input :value="configStore.selectedPreset?.loop_count" type="number" min="0" step="1" :disabled="locked" @change="changeLoop" /></label>
    <label class="compact-control"><Gauge :size="14" /><select :value="configStore.config?.acceleration || 'cpu'" :disabled="locked" @change="changeAcceleration"><option value="cpu">CPU</option><option value="gpu">GPU</option></select></label>

    <div class="toolbar-spacer" />
    <div class="button-cluster">
      <button title="撤销 Ctrl+Z" :disabled="locked || !historyStore.canUndo" @click="undo"><Undo2 :size="16" /></button>
      <button title="重做 Ctrl+Y" :disabled="locked || !historyStore.canRedo" @click="redo"><Redo2 :size="16" /></button>
      <button title="自动布局" :disabled="locked" @click="emit('auto-layout')"><LayoutTemplate :size="16" /></button>
    </div>
    <label class="readonly-toggle" title="锁定所有编辑操作"><input v-model="uiStore.readOnly" type="checkbox" :disabled="runStore.running" /><span>只读</span></label>
    <div class="button-cluster archive-controls">
      <button title="导入预设包" :disabled="locked" @click="archiveInput.click()"><ArchiveRestore :size="16" /></button>
      <button title="导出预设包" :disabled="runStore.running" @click="safe(exportArchive)"><Download :size="16" /></button>
      <button title="模板管理" @click="uiStore.templateDrawerOpen = true"><CheckCircle2 :size="16" /></button>
    </div>
    <button class="save-button" title="保存配置" :disabled="locked || !configStore.dirty" @click="safe(save)"><Save :size="16" /><span>{{ configStore.saving ? '保存中' : '保存' }}</span><i v-if="configStore.dirty" /></button>
    <button class="run-button" :class="{ stopping: runStore.running }" :title="runStore.running ? '停止运行' : '运行当前预设'" :disabled="configStore.saving" @click="safe(run)"><Square v-if="runStore.running" :size="15" fill="currentColor" /><Play v-else :size="16" fill="currentColor" /><span>{{ runStore.running ? '停止' : '运行' }}</span></button>
    <input ref="archiveInput" type="file" accept=".zip,.adb-preset.zip" hidden @change="safe(() => importArchive($event))" />
  </header>
</template>
