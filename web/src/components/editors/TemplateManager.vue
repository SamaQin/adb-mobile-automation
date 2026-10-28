<script setup>
import { computed, onMounted, ref } from 'vue'
import { Camera, ImagePlus, RefreshCw, Search, Trash2, Upload, X } from 'lucide-vue-next'
import { captureTemplate, deleteTemplate, recaptureTemplate, templateThumbnailUrl, uploadTemplate } from '../../api/templates.js'
import { useTemplateStore } from '../../stores/templateStore.js'
import { useRunStore } from '../../stores/runStore.js'
import { useConfigStore } from '../../stores/configStore.js'
import { useUiStore } from '../../stores/uiStore.js'

const emit = defineEmits(['close'])
const uiStore = useUiStore()
const runStore = useRunStore()
const configStore = useConfigStore()
const catalog = useTemplateStore()
const items = computed(() => catalog.items)
const query = ref('')
const loading = computed(() => catalog.loading)
const uploadInput = ref(null)
const pageSize = 60
const page = ref(0)
const filtered = computed(() => {
  const term = query.value.trim().toLowerCase()
  return items.value.filter((item) => (item.name || item.file).toLowerCase().includes(term))
})
const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize)))
const visibleItems = computed(() => filtered.value.slice(Math.min(page.value, pageCount.value - 1) * pageSize, (Math.min(page.value, pageCount.value - 1) + 1) * pageSize))
const locked = computed(() => runStore.running || runStore.preparing || uiStore.readOnly)

async function safe(action) {
  try { await action() } catch (error) { uiStore.notify(error.message, 'error') }
}

async function load() {
  await catalog.load({ force: true })
}

async function upload(event) {
  const files = [...(event.target.files || [])]
  event.target.value = ''
  try {
    for (const file of files) await uploadTemplate(file)
  } finally {
    catalog.invalidate()
  }
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
    let name = await uiStore.promptText({ title: '保存识别模板', label: '模板文件名', initialValue: 'template.png', confirmLabel: '保存模板' })
    if (!name) return
    if (!/\.(png|jpe?g|bmp)$/i.test(name)) name += '.png'
    await captureTemplate(name.split(/[\\/]/).pop(), captureRect, 0.8)
  }
  catalog.invalidate()
  await load()
}

async function remove(item) {
  const name = item.name || item.file
  const references = item.references || item.referenced_by || []
  const detail = references.length ? `\n引用步骤：${references.map((entry) => entry.step_name || entry.name || entry).join('、')}` : ''
  if (!await uiStore.confirmAction({ title: '删除模板？', message: `删除“${name}”后，引用它的步骤将无法识别。此操作无法通过流程撤销恢复。${detail}`, confirmLabel: '删除模板', danger: true })) return
  if (locked.value) return
  await deleteTemplate(name)
  catalog.invalidate()
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
    <aside class="template-drawer panel" :class="{ paginated: pageCount > 1 }" role="dialog" aria-modal="true" aria-label="模板管理">
      <header><div><span class="eyebrow">资源</span><h2>模板管理</h2></div><button class="icon-button" title="关闭模板管理" @click="emit('close')"><X :size="18" /></button></header>
      <div class="template-toolbar"><label class="search-field"><Search :size="14" /><input v-model="query" type="search" @input="page = 0" placeholder="筛选模板" /></label><button title="刷新列表" :disabled="loading" @click="safe(load)"><RefreshCw :size="15" /></button><button title="导入图片" :disabled="locked" @click="uploadInput.click()"><Upload :size="15" />导入</button><button class="primary" title="从设备截图创建模板" :disabled="locked" @click="safe(() => capture())"><Camera :size="15" />截图新建</button></div>
      <div class="template-grid">
        <article v-for="item in visibleItems" :key="item.name || item.file" class="template-item">
          <img :src="templateThumbnailUrl(item.name || item.file, item.revision)" :alt="item.name || item.file" loading="lazy" />
          <div><strong :title="item.name || item.file">{{ item.name || item.file }}</strong><span>{{ item.width || item.dimensions?.width || '?' }}×{{ item.height || item.dimensions?.height || '?' }} · {{ sizeText(item) }}</span><small>{{ (item.references || item.referenced_by || []).length }} 处引用</small></div>
          <div><button class="icon-button" title="重新截取" :disabled="locked" @click="safe(() => capture(item.name || item.file))"><ImagePlus :size="14" /></button><button class="icon-button danger" title="删除模板" :disabled="locked" @click="safe(() => remove(item))"><Trash2 :size="14" /></button></div>
        </article>
        <div v-if="!loading && !filtered.length" class="drawer-empty"><ImagePlus :size="28" />没有匹配的模板</div>
      </div>
      <nav v-if="pageCount > 1" class="template-pagination" aria-label="模板分页">
        <button :disabled="page === 0" @click="page = Math.max(0, page - 1)">上一页</button>
        <span>{{ Math.min(page + 1, pageCount) }} / {{ pageCount }} · {{ filtered.length }} 张模板</span>
        <button :disabled="page >= pageCount - 1" @click="page += 1">下一页</button>
      </nav>
      <input ref="uploadInput" type="file" accept="image/png,image/jpeg,image/bmp" multiple hidden @change="safe(() => upload($event))" />
    </aside>
  </div>
</template>
