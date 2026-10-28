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
  Smartphone,
  Square,
  Trash2,
  Undo2,
  Wifi,
} from 'lucide-vue-next'
import { downloadBlob } from '../../api/client.js'
import { exportPresetArchive, importPresetArchive } from '../../api/archive.js'
import { useConfigStore } from '../../stores/configStore.js'
import { useDeviceStore } from '../../stores/deviceStore.js'
import { useHistoryStore } from '../../stores/historyStore.js'
import { useRunStore } from '../../stores/runStore.js'
import { useUiStore } from '../../stores/uiStore.js'
import { useTemplateStore } from '../../stores/templateStore.js'
import { useWorkflowRun } from '../../composables/useWorkflowRun.js'

const emit = defineEmits(['auto-layout', 'layout-reorder', 'reset-layout', 'canvas-export', 'canvas-import'])
const configStore = useConfigStore()
const deviceStore = useDeviceStore()
const historyStore = useHistoryStore()
const runStore = useRunStore()
const uiStore = useUiStore()
const { startWorkflow } = useWorkflowRun()
const archiveInput = ref(null)
const locked = computed(() => uiStore.readOnly || runStore.running || runStore.preparing || configStore.saving)

async function safe(action) {
  try { await action() } catch (error) { uiStore.notify(error.message, 'error') }
}

async function switchPreset(event) {
  configStore.selectPreset(event.target.value)
  await safe(() => configStore.save())
}

async function newPreset() {
  const name = await uiStore.promptText({ title: '新建预设', message: '预设用于保存一套可以重复运行的流程。', placeholder: '例如：每日任务', confirmLabel: '创建预设' })
  if (name != null) safe(async () => { configStore.addPreset(name); await configStore.save() })
}

async function renamePreset() {
  const name = await uiStore.promptText({ title: '重命名预设', initialValue: configStore.selectedPreset.name, confirmLabel: '保存名称' })
  if (name != null) safe(() => configStore.renamePreset(configStore.selectedPreset.id, name))
}

async function deletePreset() {
  const references = await configStore.referencesForPreset(configStore.selectedPreset.id)
  const referenceText = references.length
    ? `\n\n以下步骤正在引用它：\n${references.map((item) => `${item.preset_name || item.preset} / ${item.step_name || item.step}`).join('\n')}`
    : ''
  const id = configStore.selectedPreset.id
  if (await uiStore.confirmAction({ title: '删除预设？', message: `将删除“${configStore.selectedPreset.name}”及其中的步骤。可在删除后撤销。${referenceText}`, confirmLabel: '删除预设', danger: true })) {
    if (locked.value) return
    configStore.deletePreset(id)
    const revision = configStore.revision
    uiStore.notify('预设已删除', 'info', { label: '撤销删除', run: () => {
      if (configStore.revision === revision) undo()
      else uiStore.notify('后续已有编辑，请使用撤销按钮按顺序恢复。')
    } })
  }
}

function undo() {
  const snapshot = historyStore.undo(configStore.snapshot())
  if (snapshot) { configStore.replaceFromHistory(snapshot); uiStore.clearSelection() }
}

function redo() {
  const snapshot = historyStore.redo(configStore.snapshot())
  if (snapshot) { configStore.replaceFromHistory(snapshot); uiStore.clearSelection() }
}

async function save(title = '配置已保存') {
  await deviceStore.check().catch(() => false)
  if (deviceStore.resolution) configStore.applyScreenResolution(deviceStore.resolution)
  await configStore.save()
  uiStore.notify(title, 'success')
}

async function run() {
  if (runStore.running) return safe(() => runStore.stop())
  if (runStore.preparing || configStore.saving || deviceStore.operationBusy) return
  return safe(() => startWorkflow())
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
  useTemplateStore().invalidate()
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
      <span><strong :title="deviceStore.serial || ''">{{ deviceStore.connected ? deviceStore.transport === 'wireless' ? '无线 ADB 已连接' : 'ADB 已连接' : 'ADB 未连接' }}</strong><small v-if="deviceStore.resolution">{{ deviceStore.resolution.width }}×{{ deviceStore.resolution.height }}</small><small v-else>{{ deviceStore.state }}</small></span>
      <button class="icon-button" title="检查设备" :disabled="deviceStore.checking" @click="safe(() => deviceStore.check())"><MonitorCheck :size="16" /></button>
    </div>
    <button class="icon-button" title="无线连接与设备管理" aria-label="无线连接与设备管理" :aria-expanded="uiStore.wirelessDeviceOpen" @click="uiStore.wirelessDeviceOpen = true"><Wifi :size="16" /></button>
    <button
      class="icon-button monitor-toggle"
      :class="{ active: uiStore.deviceMonitorOpen }"
      :title="uiStore.deviceMonitorOpen ? '隐藏手机实时画面' : '显示手机实时画面'"
      :aria-pressed="uiStore.deviceMonitorOpen"
      @click="uiStore.deviceMonitorOpen = !uiStore.deviceMonitorOpen"
    ><Smartphone :size="16" /></button>

    <div class="toolbar-separator" />
    <label class="preset-select"><span>预设</span><select :value="configStore.selectedPreset?.id" :disabled="runStore.running || configStore.saving || runStore.preparing" @change="switchPreset"><option v-for="preset in configStore.presets" :key="preset.id" :value="preset.id">{{ preset.name }}</option></select></label>
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
    <button class="save-button" title="保存配置" :disabled="locked || !configStore.dirty" @click="safe(save)"><Save :size="16" /><span>{{ configStore.saving ? '保存中' : configStore.dirty ? '保存修改' : '已保存' }}</span><i v-if="configStore.dirty" /></button>
    <button class="run-button" :class="{ stopping: runStore.running }" :title="runStore.running ? '停止运行' : '运行当前预设'" :disabled="configStore.saving || runStore.preparing || runStore.state === 'stopping' || deviceStore.operationBusy" @click="safe(run)"><Square v-if="runStore.running" :size="15" fill="currentColor" /><Play v-else :size="16" fill="currentColor" /><span>{{ runStore.state === 'stopping' ? '停止中…' : runStore.running ? '停止' : runStore.preparing ? '准备中…' : '运行' }}</span></button>
    <input ref="archiveInput" type="file" accept=".zip,.adb-preset.zip" hidden @change="safe(() => importArchive($event))" />
  </header>
</template>
