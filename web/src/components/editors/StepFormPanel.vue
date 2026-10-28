<script setup>
import { computed, ref, watch } from 'vue'
import { ArrowDown, ArrowUp, Camera, Copy, MonitorUp, Trash2 } from 'lucide-vue-next'
import { scaleStep } from '../../api/config.js'
import { useConfigStore } from '../../stores/configStore.js'
import { useDeviceStore } from '../../stores/deviceStore.js'
import { useRunStore } from '../../stores/runStore.js'
import { useUiStore } from '../../stores/uiStore.js'
import { cloneJson } from '../../utils/clone.js'
import BranchEditor from './BranchEditor.vue'
import RecordedActionsField from './RecordedActionsField.vue'
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
const drafts = ref({})
const errors = ref({})
const picking = ref(false)
const recognition = computed(() => (definition.value?.fields || []).some((field) => field.key === 'templates'))
watch(() => props.nodeId, () => { drafts.value = {}; errors.value = {} })
function valueOf(field) { return step.value?.params?.[field.key] ?? field.default }
function isVisible(field) {
  const params = step.value?.params || {}
  if (['click_count', 'click_interval'].includes(field.key)) return params.tap_mode === 'multi'
  if (['click_x', 'click_y'].includes(field.key)) return Boolean(params.custom_click)
  if (field.key.startsWith('search_')) return Boolean(params.roi_enabled)
  if (['tap_between_x', 'tap_between_y'].includes(field.key)) return Boolean(params.tap_between)
  if (recognition.value && ['x1', 'y1', 'x2', 'y2', 'duration'].includes(field.key)) return Boolean(params.swipe_between)
  return true
}
function groupKey(field) {
  if (!recognition.value) return 'parameters'
  if (field.coordinate_offset || field.key.startsWith('offset_')) return 'advanced'
  if (['tap_between', 'tap_between_x', 'tap_between_y', 'swipe_between', 'x1', 'y1', 'x2', 'y2', 'duration'].includes(field.key)) return 'retry'
  if (['custom_click', 'click_x', 'click_y', 'tap_mode', 'click_count', 'click_interval', 'wait_after'].includes(field.key)) return 'action'
  return 'core'
}
function toEntries(fields) {
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
}
const editorGroups = computed(() => {
  const groups = recognition.value ? [
    { key: 'core', label: '识别目标', hint: '先选择模板；阈值为 0–1，越高越严格。未限定区域时搜索全屏。' },
    { key: 'action', label: '识别成功后', hint: '默认点击匹配中心；可改为固定位置或连击。' },
    { key: 'retry', label: '重试前动作', collapsible: true, hint: '识别失败且还要重试时，先点击或滑动，再重新识别。' },
    { key: 'advanced', label: '高级点击偏移', collapsible: true, hint: '在点击位置上增加偏移，单位为原始设备像素；负数向左或向上。' },
  ] : [{ key: 'parameters' }]
  return groups.map((group) => {
    const fields = (definition.value?.fields || []).filter((field) => groupKey(field) === group.key)
    const configured = fields.filter((field) => JSON.stringify(valueOf(field)) !== JSON.stringify(field.default))
    const retained = configured.filter((field) => !isVisible(field))
    return { ...group, fields, configured, retained, entries: toEntries(fields.filter(isVisible)) }
  }).filter((group) => group.fields.length)
})
const disabled = computed(() => uiStore.readOnly || runStore.running || runStore.preparing || configStore.saving)
const disabledReason = computed(() => runStore.running ? '运行中暂不能修改参数或选取坐标，请停止后编辑。' : runStore.preparing ? '正在准备运行，请稍候再编辑。' : uiStore.readOnly ? '当前为只读模式，可以查看参数，不能修改。' : configStore.saving ? '正在保存，请稍候再编辑。' : '')
const resolutionMismatch = computed(() => {
  const saved = step.value?.screen_resolution
  const current = deviceStore.resolution
  return saved && current && (saved.width !== current.width || saved.height !== current.height)
})

function hintFor(field) {
  const hints = {
    require_all: '关闭：任意一张匹配即可；开启：所有模板都要匹配。',
    roi_enabled: 'ROI 是只搜索的矩形区域，可从截图框选；使用原始设备像素。',
    attempts: '默认 1 次；0 表示无限重试，直到识别成功或手动停止。',
    interval: '两次识别之间的等待时间，单位：秒。',
    custom_click: '关闭时点击模板中心；开启后使用下方固定坐标。',
    tap_between: '每次重试前先点击指定位置。', swipe_between: '每次重试前先按指定路线滑动。',
  }
  if (hints[field.key]) return hints[field.key]
  if (field.kind === 'recording') return '第一次输入开始计时，最后一次输入结束；重录会整段替换。'
  if (field.coordinate_axis) return field.coordinate_offset ? '原始设备像素；允许负数。' : '单位：原始设备像素。'
  if (field.key === 'duration') return '单位：毫秒；1000 毫秒 = 1 秒。'
  if (['wait_after', 'seconds', 'click_interval'].includes(field.key)) return '单位：秒；0 表示不等待。'
  if (field.key === 'click_count') return '至少点击 1 次。'
  return ''
}
function bounds(field) {
  const offset = field.coordinate_offset || field.key.startsWith('offset_')
  return {
    min: field.min ?? field.minimum ?? (offset ? undefined : ['click_count', 'search_width', 'search_height'].includes(field.key) ? 1 : 0),
    max: field.max ?? field.maximum ?? (field.key.includes('threshold') ? 1 : undefined),
  }
}
function inputValue(field) { return drafts.value[field.key] ?? valueOf(field) }
function validateNumber(field, value) {
  if (String(value).trim() === '') return '请填写数值，不能留空。'
  const number = Number(value)
  if (!Number.isFinite(number)) return '请输入有效的有限数值。'
  if (field.kind === 'int' && !Number.isSafeInteger(number)) return '请输入整数，不能包含小数。'
  const { min, max } = bounds(field)
  if (min != null && number < min) return `数值不能小于 ${min}。`
  if (max != null && number > max) return `数值不能大于 ${max}。`
  return ''
}
function previewNumber(field, value) {
  drafts.value[field.key] = value
  const error = validateNumber(field, value)
  if (error) errors.value[field.key] = error
  else delete errors.value[field.key]
}
function updateNumber(field, value) {
  previewNumber(field, value)
  if (errors.value[field.key] || disabled.value) return
  updateParam(field.key, Number(value))
  delete drafts.value[field.key]
}
function updateTemplates(templates) {
  if (disabled.value) return
  if (templates.some((template) => template.threshold == null || String(template.threshold).trim() === '' || !Number.isFinite(Number(template.threshold)) || Number(template.threshold) < 0 || Number(template.threshold) > 1)) {
    errors.value.templates = '模板阈值必须是 0 到 1 之间的数值。'
    return
  }
  delete errors.value.templates
  configStore.updateTemplates(props.nodeId, templates)
}
function updateCommon(key, value) {
  if (disabled.value) return
  configStore.mutateStep(props.nodeId, (item) => {
    item[key] = key === 'enabled' ? Boolean(value) : value
    if (key === 'on_failure' && !definition.value?.can_fail) item.on_failure = 'stop'
  })
}

function updateParam(key, value) {
  if (disabled.value) return
  configStore.mutateStep(props.nodeId, (item) => { item.params[key] = value })
}

async function ensureDevice() {
  try {
    if (!deviceStore.connected) await deviceStore.check()
    if (deviceStore.connected) return true
    uiStore.notify('设备未连接，请先连接设备并允许 USB 调试，再从截图选择。', 'error')
  } catch (error) {
    uiStore.notify(`无法连接设备：${error.message}。请检查 USB 调试后重试。`, 'error')
  }
  return false
}

async function pickCoordinates(fields) {
  if (disabled.value || picking.value) return
  const nodeId = props.nodeId
  picking.value = true
  try {
    if (!await ensureDevice() || disabled.value || nodeId !== props.nodeId) return
    const mode = fields.some((field) => field.key.startsWith('search_')) ? 'rect'
      : fields.some((field) => ['x1', 'y1', 'x2', 'y2'].includes(field.key)) ? 'swipe' : 'point'
    const title = mode === 'rect' ? '选择识别搜索区域' : mode === 'swipe' ? '选择滑动起点和终点' : '选择坐标'
    const result = await new Promise((resolve) => uiStore.openScreenshot({ mode, title, resolve }))
    if (!result || disabled.value || nodeId !== props.nodeId) return
    configStore.mutateStep(nodeId, (item) => {
      if (mode === 'rect') Object.assign(item.params, { search_x: result.x, search_y: result.y, search_width: result.width, search_height: result.height })
      for (const field of fields) {
        if (mode === 'swipe' && result[field.key] != null) item.params[field.key] = result[field.key]
        else if (mode === 'point') item.params[field.key] = result[field.coordinate_axis]
        delete drafts.value[field.key]
        delete errors.value[field.key]
      }
      item.screen_resolution = result.resolution
    }, '拾取坐标')
  } finally { picking.value = false }
}

function updatePreset(value) {
  if (disabled.value) return
  const preset = configStore.presets.find((item) => item.id === value)
  configStore.mutateStep(props.nodeId, (item) => {
    item.params.preset_id = value
    item.params.preset_name = preset?.name || item.params.preset_name || ''
  })
}

async function adaptResolution() {
  if (disabled.value || scaling.value) return
  scaling.value = true
  const nodeId = props.nodeId
  try {
    if (!await ensureDevice()) return
    if (!deviceStore.resolution) throw new Error('设备未返回分辨率')
    const scaled = await scaleStep(cloneJson(step.value), deviceStore.resolution)
    if (disabled.value || nodeId !== props.nodeId) return
    configStore.mutateStep(nodeId, (item) => Object.assign(item, scaled), '适配分辨率')
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
    <p v-if="disabledReason" class="editor-notice" role="status">{{ disabledReason }}</p>
    <div v-if="resolutionMismatch" class="inline-alert warning-alert">
      <MonitorUp :size="15" /><span>设备分辨率已变化</span>
      <button :disabled="disabled || scaling" @click="adaptResolution">适配</button>
    </div>
    <section class="form-section">
      <div class="section-title"><span>步骤</span><small>#{{ step.id.slice(0, 8) }}</small></div>
      <label class="field"><span>名称</span><input :value="step.name" :disabled="disabled" @change="updateCommon('name', $event.target.value.trim() || '未命名步骤')" /></label>
      <label class="toggle-field"><span><strong>启用</strong><small>停用后运行时跳过</small></span><input type="checkbox" :checked="step.enabled" :disabled="disabled" @change="updateCommon('enabled', $event.target.checked)" /></label>
      <label class="field"><span>执行失败时</span><select :value="step.on_failure" :disabled="disabled || !definition?.can_fail" @change="updateCommon('on_failure', $event.target.value)"><option value="stop">停止预设</option><option value="continue">跳到下一步</option></select><small class="field-help">{{ definition?.can_fail ? '跳到下一步：记录本步失败后继续执行；依赖本步成功的步骤仍会跳过。' : '此步骤不支持失败后继续。' }}</small></label>
      <div v-if="step.depends_on?.length" class="dependency-copy"><strong>前置依赖</strong><p>只有以下步骤都成功，本步才会执行：{{ step.depends_on.map((id) => found.list?.find((item) => item.id === id)?.name || id).join('、') }}。</p></div>
    </section>

    <section class="form-section">
      <div class="section-title"><span>{{ definition?.label || step.kind }}参数</span><small>{{ definition?.fields?.length || 0 }}</small></div>
      <component :is="group.collapsible ? 'details' : 'div'" v-for="group in editorGroups" :key="`${nodeId}:${group.key}`" class="parameter-group" :data-group="group.key" :open="group.collapsible && group.configured.length > 0 ? true : undefined">
        <summary v-if="group.collapsible" class="group-heading">{{ group.label }}<small>{{ group.configured.length ? `已配置 ${group.configured.length} 项` : '按需展开' }}</small></summary>
        <h3 v-else-if="recognition" class="group-heading">{{ group.label }}</h3>
        <p v-if="group.hint" class="field-help group-help">{{ group.hint }}</p>
        <p v-if="group.retained.length" class="retained-settings" role="note">已保留未启用的设置：{{ group.retained.map((field) => `${field.label} = ${valueOf(field)}`).join('、') }}。开启对应选项可编辑。</p>
      <template v-for="entry in group.entries" :key="entry.key">
        <div v-if="entry.coordinates" class="coordinate-group">
          <div>
            <label v-for="field in entry.coordinates" :key="field.key" class="field"><span>{{ field.label }}</span><input :value="inputValue(field)" :name="field.key" type="number" :step="field.kind === 'int' ? 1 : 'any'" :min="bounds(field).min" :max="bounds(field).max" :aria-invalid="Boolean(errors[field.key])" :aria-describedby="`${nodeId}-${field.key}-feedback`" :disabled="disabled" @input="previewNumber(field, $event.target.value)" @change="updateNumber(field, $event.target.value)" /><small :id="`${nodeId}-${field.key}-feedback`" :class="errors[field.key] ? 'field-error' : 'field-help'">{{ errors[field.key] || hintFor(field) }}</small></label>
          </div>
          <button class="icon-button coordinate-group-picker" :title="`从截图选取${entry.coordinates.map((field) => field.label).join('、')}`" :disabled="disabled || picking" @click="pickCoordinates(entry.coordinates)"><Camera :size="15" /></button>
        </div>
        <div v-else-if="entry.field.kind === 'templates'" class="template-field" :aria-invalid="Boolean(errors.templates)">
          <TemplatePicker :model-value="step.params[entry.field.key] || []" :disabled="disabled" @update:model-value="updateTemplates" />
          <p v-if="errors.templates" class="field-error" role="alert">{{ errors.templates }}</p>
        </div>
        <div v-else-if="entry.field.kind === 'recording'" class="recording-field">
          <RecordedActionsField :node-id="nodeId" :step="step" :disabled="disabled" />
        </div>
        <div v-else-if="entry.field.kind === 'choice'" class="choice-field">
          <span>{{ entry.field.label }}</span>
          <div><label v-for="option in entry.field.options || []" :key="option.value"><input type="radio" :name="`${nodeId}-${entry.field.key}`" :value="option.value" :checked="valueOf(entry.field) === option.value" :disabled="disabled" @change="updateParam(entry.field.key, option.value, entry.field.kind)" /><span>{{ option.label }}</span></label></div>
        </div>
        <label v-else-if="entry.field.kind === 'bool'" class="toggle-field"><span><strong>{{ entry.field.key === 'require_all' ? '所有模板都匹配才算成功' : entry.field.label }}</strong><small v-if="hintFor(entry.field)">{{ hintFor(entry.field) }}</small></span><input type="checkbox" :name="entry.field.key" :checked="Boolean(valueOf(entry.field))" :disabled="disabled" @change="updateParam(entry.field.key, $event.target.checked)" /></label>
        <label v-else-if="entry.field.kind === 'preset'" class="field"><span>{{ entry.field.label }}</span><select :value="step.params[entry.field.key]" :disabled="disabled" @change="updatePreset($event.target.value)"><option value="">选择预设</option><option v-for="preset in configStore.presets" :key="preset.id" :value="preset.id" :disabled="preset.id === configStore.selectedPreset.id">{{ preset.name }}</option></select></label>
        <label v-else class="field"><span>{{ entry.field.label }}</span><input :value="inputValue(entry.field)" :name="entry.field.key" type="number" :step="entry.field.kind === 'int' ? 1 : 'any'" :min="bounds(entry.field).min" :max="bounds(entry.field).max" :aria-invalid="Boolean(errors[entry.field.key])" :aria-describedby="`${nodeId}-${entry.field.key}-feedback`" :disabled="disabled" @input="previewNumber(entry.field, $event.target.value)" @change="updateNumber(entry.field, $event.target.value)" /><small :id="`${nodeId}-${entry.field.key}-feedback`" :class="errors[entry.field.key] ? 'field-error' : 'field-help'">{{ errors[entry.field.key] || hintFor(entry.field) }}</small></label>
      </template>
      </component>
      <p v-if="!definition?.fields?.length" class="empty-copy">此步骤没有可配置参数。</p>
    </section>

    <BranchEditor v-if="step.kind === 'find_and_tap'" :node-id="nodeId" :step="step" :disabled="disabled" />

    <div class="form-actions">
      <button title="上移步骤" :disabled="disabled" @click="configStore.moveStep(nodeId, -1)"><ArrowUp :size="14" />上移</button>
      <button title="下移步骤" :disabled="disabled" @click="configStore.moveStep(nodeId, 1)"><ArrowDown :size="14" />下移</button>
      <button title="复制步骤" :disabled="disabled" @click="configStore.duplicateStep(nodeId)"><Copy :size="14" />复制</button>
      <button class="danger" title="删除步骤" :disabled="disabled" @click="configStore.deleteSteps([nodeId]); uiStore.clearSelection(); uiStore.notify('步骤已删除，可用 Ctrl+Z 撤销')"><Trash2 :size="14" />删除</button>
    </div>
  </div>
</template>

<style scoped>
.editor-notice, .retained-settings { margin: 0 0 12px; padding: 9px 10px; border: 1px solid var(--border, #334155); border-radius: 7px; font-size: 12px; line-height: 1.6; color: var(--muted, #94a3b8); overflow-wrap: anywhere; }
.parameter-group + .parameter-group { margin-top: 17px; padding-top: 15px; border-top: 1px solid var(--border, #334155); }
.group-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin: 0 0 10px; font-size: 12px; font-weight: 650; }
summary.group-heading { cursor: pointer; display: list-item; }
.group-heading small { margin-left: 8px; font-size: 10px; font-weight: 400; color: var(--muted, #94a3b8); }
.field-help { display: block; font-size: 11px; font-weight: 400; line-height: 1.55; color: var(--muted, #94a3b8); }
.group-help { margin: 0 0 12px; }
.field > .field-help, .field > .field-error { grid-column: 1 / -1; margin: -2px 0 5px; }
.toggle-field { gap: 12px; padding: 7px 0; }
.toggle-field > span { flex: 1; min-width: 0; gap: 3px; }
.toggle-field > input { flex: none; }
.toggle-field strong { font-weight: 550; }
.field-help { overflow-wrap: anywhere; }
.form-section > .field { margin-bottom: 8px; }
.field-error { display: block; color: #fb7185; font-size: 11px; line-height: 1.55; }
input[aria-invalid="true"] { border-color: #fb7185; }
.dependency-copy { font-size: 11px; line-height: 1.6; color: var(--muted, #94a3b8); }
.dependency-copy p { margin: 4px 0 0; }
</style>
