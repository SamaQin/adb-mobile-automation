<script setup>
import { computed, onMounted, ref } from 'vue'
import { FolderOpen, Plus, RefreshCw, Trash2 } from 'lucide-vue-next'
import { templateThumbnailUrl } from '../../api/templates.js'
import { useTemplateStore } from '../../stores/templateStore.js'
import { useUiStore } from '../../stores/uiStore.js'
import { cloneJson } from '../../utils/clone.js'

const props = defineProps({ modelValue: { type: Array, default: () => [] }, disabled: Boolean })
const emit = defineEmits(['update:modelValue'])
const catalog = useTemplateStore()
const ui = useUiStore()
const thresholdError = ref('')
const templateExists = (file) => !catalog.loadedAt || catalog.byName.has(file)
async function reload() { try { await catalog.load({ force: true }) } catch { /* Inline error stays visible. */ } }
const templates = computed(() => catalog.items)
const selected = ref('')
const thresholdDrafts = ref({})
const available = computed(() => {
  const selectedFiles = new Set(props.modelValue.map((item) => item.file))
  return templates.value.filter((item) => !selectedFiles.has(item.name || item.file))
})

onMounted(async () => {
  try { await catalog.load() } catch { /* Keep any previously loaded catalog. */ }
})

function add() {
  if (!selected.value) return
  emit('update:modelValue', [...props.modelValue, { file: selected.value, threshold: 0.8 }])
  selected.value = ''
}

function updateThreshold(index, value) {
  const threshold = Number(value)
  if (!Number.isFinite(threshold) || threshold < 0 || threshold > 1) {
    thresholdError.value = '相似度阈值应在 0 到 1 之间。'
    return
  }
  thresholdError.value = ''
  const next = cloneJson(props.modelValue)
  next[index].threshold = threshold
  emit('update:modelValue', next)
}

function thresholdValue(template) {
  const value = thresholdDrafts.value[template.file] ?? Number(template.threshold ?? 0.8)
  return Number.isFinite(value) ? value : 0.8
}

function previewThreshold(template, value) {
  thresholdDrafts.value[template.file] = Number(value)
}

function commitThreshold(index, template, value) {
  updateThreshold(index, value)
  delete thresholdDrafts.value[template.file]
}

function remove(index) {
  emit('update:modelValue', props.modelValue.filter((_, itemIndex) => itemIndex !== index))
}
</script>

<template>
  <div class="template-picker">
    <div v-for="(template, index) in modelValue" :key="template.file" class="template-pick-row">
      <img :src="templateThumbnailUrl(template.file, catalog.byName.get(template.file)?.revision)" :alt="template.file" />
      <div><strong :title="template.file">{{ template.file }}</strong><span>{{ thresholdValue(template).toFixed(2) }}<small v-if="!templateExists(template.file)" class="template-missing"> · 文件缺失</small></span></div>
      <input :value="thresholdValue(template)" type="range" min="0" max="1" step="0.01" :disabled="disabled" :aria-label="`${template.file} 阈值`" @input="previewThreshold(template, $event.target.value)" @change="commitThreshold(index, template, $event.target.value)" />
      <button class="icon-button danger" title="移除模板" :disabled="disabled" @click="remove(index)"><Trash2 :size="14" /></button>
    </div>
    <p v-if="thresholdError" class="template-feedback error" role="alert">{{ thresholdError }}</p>
    <p v-if="catalog.error" class="template-feedback error" role="alert">模板列表加载失败。<button type="button" @click="reload"><RefreshCw :size="12" />重试</button></p>
    <p v-else-if="!catalog.loading && !templates.length" class="template-feedback">还没有模板，先从设备截图创建或导入图片。</p>
    <div class="template-add-row">
      <select v-model="selected" :disabled="disabled"><option value="">{{ catalog.loading ? '正在加载模板…' : '选择模板' }}</option><option v-for="item in available" :key="item.name || item.file" :value="item.name || item.file">{{ item.name || item.file }}</option></select>
      <button class="icon-button" title="添加模板" :disabled="disabled || !selected" @click="add"><Plus :size="15" /></button>
    </div>
    <button type="button" class="template-manage-link" @click="ui.templateDrawerOpen = true"><FolderOpen :size="13" />管理或创建模板</button>
  </div>
</template>

<style scoped>
.template-feedback { margin:6px 0; font-size:11px; line-height:1.6; color:var(--muted); }
.template-feedback.error, .template-missing { color:var(--red); }
.template-feedback button { font-size:11px; min-height:22px; padding:0 5px; margin-left:5px; }
.template-manage-link { margin-top:7px; padding:3px 6px; min-height:25px; color:var(--cyan); border-color:transparent; background:transparent; font-size:11px; }
</style>
