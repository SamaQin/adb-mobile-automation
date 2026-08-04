<script setup>
import { computed, onMounted, ref } from 'vue'
import { Plus, Trash2 } from 'lucide-vue-next'
import { fetchTemplates, templateThumbnailUrl } from '../../api/templates.js'
import { cloneJson } from '../../utils/clone.js'

const props = defineProps({ modelValue: { type: Array, default: () => [] }, disabled: Boolean })
const emit = defineEmits(['update:modelValue'])
const templates = ref([])
const selected = ref('')
const thresholdDrafts = ref({})
const available = computed(() => templates.value.filter((item) => !props.modelValue.some((selectedItem) => selectedItem.file === (item.name || item.file))))

onMounted(async () => {
  try { templates.value = await fetchTemplates() } catch { templates.value = [] }
})

function add() {
  if (!selected.value) return
  emit('update:modelValue', [...props.modelValue, { file: selected.value, threshold: 0.8 }])
  selected.value = ''
}

function updateThreshold(index, value) {
  const next = cloneJson(props.modelValue)
  next[index].threshold = Number(value)
  emit('update:modelValue', next)
}

function thresholdValue(template) {
  return thresholdDrafts.value[template.file] ?? Number(template.threshold ?? 0.8)
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
      <img :src="templateThumbnailUrl(template.file)" :alt="template.file" />
      <div><strong :title="template.file">{{ template.file }}</strong><span>{{ thresholdValue(template).toFixed(2) }}</span></div>
      <input :value="thresholdValue(template)" type="range" min="0" max="1" step="0.01" :disabled="disabled" :aria-label="`${template.file} 阈值`" @input="previewThreshold(template, $event.target.value)" @change="commitThreshold(index, template, $event.target.value)" />
      <button class="icon-button danger" title="移除模板" :disabled="disabled" @click="remove(index)"><Trash2 :size="14" /></button>
    </div>
    <div class="template-add-row">
      <select v-model="selected" :disabled="disabled"><option value="">选择模板</option><option v-for="item in available" :key="item.name || item.file" :value="item.name || item.file">{{ item.name || item.file }}</option></select>
      <button class="icon-button" title="添加模板" :disabled="disabled || !selected" @click="add"><Plus :size="15" /></button>
    </div>
  </div>
</template>
