<script setup>
import { computed, ref } from 'vue'
import { ArrowDown, ArrowUp, Camera, Copy, MonitorUp, Trash2 } from 'lucide-vue-next'
import { scaleStep } from '../../api/config.js'
import { useConfigStore } from '../../stores/configStore.js'
import { useDeviceStore } from '../../stores/deviceStore.js'
import { useRunStore } from '../../stores/runStore.js'
import { useUiStore } from '../../stores/uiStore.js'
import { cloneJson } from '../../utils/clone.js'
import BranchEditor from './BranchEditor.vue'
import TemplatePicker from './TemplatePicker.vue'

const props = defineProps({ nodeId: { type: String, required: true } })
const configStore = useConfigStore()
const deviceStore = useDeviceStore()
const runStore = useRunStore()
const uiStore = useUiStore()
const scaling = ref(false)
const found = computed(() => configStore.findStep(props.nodeId))
const step = computed(() => found.value.step)
const definition = computed(() => configStore.definitionMap.get(step.value?.kind))
const editorEntries = computed(() => {
  const fields = (definition.value?.fields || []).filter((field) => (
    (!['click_count', 'click_interval'].includes(field.key) || step.value?.params?.tap_mode === 'multi')
    && (!['click_x', 'click_y'].includes(field.key) || step.value?.params?.custom_click)
  ))
  const entries = []
  for (let index = 0; index < fields.length;) {
    const field = fields[index]
    if (!field.coordinate_axis || field.coordinate_offset) {
      entries.push({ key: field.key, field })
      index += 1
      continue
    }
    const coordinates = []
    while (index < fields.length && fields[index].coordinate_axis && !fields[index].coordinate_offset) {
      coordinates.push(fields[index])
      index += 1
    }
    entries.push({ key: `coordinates:${coordinates.map((item) => item.key).join(':')}`, coordinates })
  }
  return entries
})
const disabled = computed(() => uiStore.readOnly || runStore.running || configStore.saving)
const resolutionMismatch = computed(() => {
  const saved = step.value?.screen_resolution
  const current = deviceStore.resolution
  return saved && current && (saved.width !== current.width || saved.height !== current.height)
})

function updateCommon(key, value) {
  configStore.mutateStep(props.nodeId, (item) => {
    item[key] = key === 'enabled' ? Boolean(value) : value
    if (key === 'on_failure' && !definition.value?.can_fail) item.on_failure = 'stop'
  })
}

function updateParam(key, value, kind) {
  const parsed = kind === 'int' ? Number.parseInt(value, 10) : kind === 'float' ? Number(value) : value
  configStore.mutateStep(props.nodeId, (item) => { item.params[key] = parsed })
}

async function pickCoordinates(fields) {
  const mode = fields.some((field) => ['x1', 'y1', 'x2', 'y2'].includes(field.key)) ? 'swipe' : 'point'
  const title = mode === 'swipe' ? '选择滑动起点和终点' : '选择坐标'
  const result = await new Promise((resolve) => uiStore.openScreenshot({ mode, title, resolve }))
  if (!result) return
  configStore.mutateStep(props.nodeId, (item) => {
    for (const field of fields) {
      if (mode === 'swipe' && result[field.key] != null) item.params[field.key] = result[field.key]
      else if (mode === 'point') item.params[field.key] = result[field.coordinate_axis]
    }
    item.screen_resolution = result.resolution
  }, '拾取坐标')
}

function updatePreset(value) {
  const preset = configStore.presets.find((item) => item.id === value)
  configStore.mutateStep(props.nodeId, (item) => {
    item.params.preset_id = value
    item.params.preset_name = preset?.name || item.params.preset_name || ''
  })
}

async function adaptResolution() {
  if (!deviceStore.connected) await deviceStore.check()
  if (!deviceStore.resolution) throw new Error('设备未返回分辨率')
  scaling.value = true
  try {
    const scaled = await scaleStep(cloneJson(step.value), deviceStore.resolution)
    configStore.mutateStep(props.nodeId, (item) => Object.assign(item, scaled), '适配分辨率')
    uiStore.notify('坐标已适配当前设备分辨率', 'success')
  } catch (error) {
    uiStore.notify(error.message, 'error')
  } finally {
    scaling.value = false
  }
}
</script>

<template>
  <div v-if="step" class="step-form">
    <div v-if="resolutionMismatch" class="inline-alert warning-alert">
      <MonitorUp :size="15" /><span>设备分辨率已变化</span>
      <button :disabled="disabled || scaling" @click="adaptResolution">适配</button>
    </div>
    <section class="form-section">
      <div class="section-title"><span>步骤</span><small>#{{ step.id.slice(0, 8) }}</small></div>
      <label class="field"><span>名称</span><input :value="step.name" :disabled="disabled" @change="updateCommon('name', $event.target.value.trim() || '未命名步骤')" /></label>
      <label class="toggle-field"><span><strong>启用</strong><small>停用后运行时跳过</small></span><input type="checkbox" :checked="step.enabled" :disabled="disabled" @change="updateCommon('enabled', $event.target.checked)" /></label>
      <label class="field"><span>执行失败时</span><select :value="step.on_failure" :disabled="disabled || !definition?.can_fail" @change="updateCommon('on_failure', $event.target.value)"><option value="stop">停止预设</option><option value="continue">跳到下一步</option></select></label>
    </section>

    <section class="form-section">
      <div class="section-title"><span>{{ definition?.label || step.kind }}参数</span><small>{{ definition?.fields?.length || 0 }}</small></div>
      <template v-for="entry in editorEntries" :key="entry.key">
        <div v-if="entry.coordinates" class="coordinate-group">
          <div>
            <label v-for="field in entry.coordinates" :key="field.key" class="field"><span>{{ field.label }}</span><input :value="step.params[field.key] ?? field.default" type="number" :step="field.kind === 'int' ? 1 : 'any'" :disabled="disabled" @change="updateParam(field.key, $event.target.value, field.kind)" /></label>
          </div>
          <button class="icon-button coordinate-group-picker" :title="`从截图选取${entry.coordinates.map((field) => field.label).join('、')}`" :disabled="disabled" @click="pickCoordinates(entry.coordinates)"><Camera :size="15" /></button>
        </div>
        <TemplatePicker v-else-if="entry.field.kind === 'templates'" :model-value="step.params[entry.field.key] || []" :disabled="disabled" @update:model-value="configStore.updateTemplates(nodeId, $event)" />
        <div v-else-if="entry.field.kind === 'choice'" class="choice-field">
          <span>{{ entry.field.label }}</span>
          <div><label v-for="option in entry.field.options || []" :key="option.value"><input type="radio" :name="`${nodeId}-${entry.field.key}`" :value="option.value" :checked="step.params[entry.field.key] === option.value || (!step.params[entry.field.key] && option.value === entry.field.default)" :disabled="disabled" @change="updateParam(entry.field.key, option.value, entry.field.kind)" /><span>{{ option.label }}</span></label></div>
        </div>
        <label v-else-if="entry.field.kind === 'bool'" class="toggle-field"><span><strong>{{ entry.field.label }}</strong></span><input type="checkbox" :checked="Boolean(step.params[entry.field.key])" :disabled="disabled" @change="updateParam(entry.field.key, $event.target.checked, entry.field.kind)" /></label>
        <label v-else-if="entry.field.kind === 'preset'" class="field"><span>{{ entry.field.label }}</span><select :value="step.params[entry.field.key]" :disabled="disabled" @change="updatePreset($event.target.value)"><option value="">选择预设</option><option v-for="preset in configStore.presets" :key="preset.id" :value="preset.id" :disabled="preset.id === configStore.selectedPreset.id">{{ preset.name }}</option></select></label>
        <label v-else class="field"><span>{{ entry.field.label }}</span><input :value="step.params[entry.field.key] ?? entry.field.default" type="number" :step="entry.field.kind === 'int' ? 1 : 'any'" :disabled="disabled" @change="updateParam(entry.field.key, $event.target.value, entry.field.kind)" /></label>
      </template>
      <p v-if="!definition?.fields?.length" class="empty-copy">此步骤没有可配置参数。</p>
    </section>

    <BranchEditor v-if="step.kind === 'find_and_tap'" :node-id="nodeId" :step="step" :disabled="disabled" />

    <div class="form-actions">
      <button title="上移步骤" :disabled="disabled" @click="configStore.moveStep(nodeId, -1)"><ArrowUp :size="14" />上移</button>
      <button title="下移步骤" :disabled="disabled" @click="configStore.moveStep(nodeId, 1)"><ArrowDown :size="14" />下移</button>
      <button title="复制步骤" :disabled="disabled" @click="configStore.duplicateStep(nodeId)"><Copy :size="14" />复制</button>
      <button class="danger" title="删除步骤" :disabled="disabled" @click="configStore.deleteSteps([nodeId]); uiStore.clearSelection()"><Trash2 :size="14" />删除</button>
    </div>
  </div>
</template>
