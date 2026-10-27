<script setup>
import { computed, onMounted, ref } from 'vue'
import { Camera, ImagePlus, RefreshCw, Search, Trash2, Upload, X } from 'lucide-vue-next'
import { captureTemplate, deleteTemplate, fetchTemplates, recaptureTemplate, templateThumbnailUrl, uploadTemplate } from '../../api/templates.js'
import { useRunStore } from '../../stores/runStore.js'
import { useConfigStore } from '../../stores/configStore.js'
import { useUiStore } from '../../stores/uiStore.js'

const emit = defineEmits(['close'])
const uiStore = useUiStore()
const runStore = useRunStore()
const configStore = useConfigStore()
const items = ref([])
const query = ref('')
const loading = ref(false)
const uploadInput = ref(null)
const filtered = computed(() => items.value.filter((item) => (item.name || item.file).toLowerCase().includes(query.value.toLowerCase())))
const locked = computed(() => runStore.running || uiStore.readOnly)

async function safe(action) {
  try { await action() } catch (error) { uiStore.notify(error.message, 'error') }
}

async function load() {
  loading.value = true
  try { items.value = await fetchTemplates() } finally { loading.value = false }
}

async function upload(event) {
  const files = [...(event.target.files || [])]
  event.target.value = ''
  for (const file of files) await uploadTemplate(file)
  await load()
}

async function capture(existing = null) {
  const rect = await new Promise((resolve) => uiStore.openScreenshot({ mode: 'rect', title: existing ? `重新截取 ${existing}` : '从截图创建模板', resolve }))
  if (!rect) return
  const captureRect = { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
  if (existing) {
    await recaptureTemplate(existing, captureRect, 0.8)
    configStore.updateTemplateResolution(existing, rect.resolution)
  }
  else {
    let name = window.prompt('模板文件名', 'template.png')
    if (!name) return
    if (!/\.(png|jpe?g|bmp)$/i.test(name)) name += '.png'
    await captureTemplate(name.split(/[\\/]/).pop(), captureRect, 0.8)
  }
  await load()
}

async function remove(item) {
  const name = item.name || item.file
  const references = item.references || item.referenced_by || []
  const detail = references.length ? `\n引用步骤：${references.map((entry) => entry.step_name || entry.name || entry).join('、')}` : ''
  if (!window.confirm(`删除模板“${name}”？引用它的步骤将无法识别。${detail}`)) return
  await deleteTemplate(name)
  await load()
}

function sizeText(item) {
  const bytes = item.size_bytes ?? item.size ?? 0
  return bytes ? `${Math.max(1, Math.round(bytes / 1024))} KB` : '未知大小'
}

onMounted(() => safe(load))
</script>

<template>
  <div class="drawer-backdrop" @mousedown.self="emit('close')">
    <aside class="template-drawer panel" role="dialog" aria-modal="true" aria-label="模板管理">
      <header><div><span class="eyebrow">资源</span><h2>模板管理</h2></div><button class="icon-button" title="关闭模板管理" @click="emit('close')"><X :size="18" /></button></header>
      <div class="template-toolbar"><label class="search-field"><Search :size="14" /><input v-model="query" type="search" placeholder="筛选模板" /></label><button title="刷新列表" :disabled="loading" @click="safe(load)"><RefreshCw :size="15" /></button><button title="导入图片" :disabled="locked" @click="uploadInput.click()"><Upload :size="15" />导入</button><button class="primary" title="从设备截图创建模板" :disabled="locked" @click="safe(() => capture())"><Camera :size="15" />截图新建</button></div>
      <div class="template-grid">
        <article v-for="item in filtered" :key="item.name || item.file" class="template-item">
          <img :src="templateThumbnailUrl(item.name || item.file)" :alt="item.name || item.file" loading="lazy" />
          <div><strong :title="item.name || item.file">{{ item.name || item.file }}</strong><span>{{ item.width || item.dimensions?.width || '?' }}×{{ item.height || item.dimensions?.height || '?' }} · {{ sizeText(item) }}</span><small>{{ (item.references || item.referenced_by || []).length }} 处引用</small></div>
          <div><button class="icon-button" title="重新截取" :disabled="locked" @click="safe(() => capture(item.name || item.file))"><ImagePlus :size="14" /></button><button class="icon-button danger" title="删除模板" :disabled="locked" @click="safe(() => remove(item))"><Trash2 :size="14" /></button></div>
        </article>
        <div v-if="!loading && !filtered.length" class="drawer-empty"><ImagePlus :size="28" />没有匹配的模板</div>
      </div>
      <input ref="uploadInput" type="file" accept="image/png,image/jpeg,image/bmp" multiple hidden @change="safe(() => upload($event))" />
    </aside>
  </div>
</template>
