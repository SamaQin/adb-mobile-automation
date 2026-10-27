<script setup>
import { computed, ref } from 'vue'
import { Boxes, PanelLeftClose, PanelLeftOpen, Plus, Search, X } from 'lucide-vue-next'
import { appearanceFor, descriptionFor, matchesStepSearch } from '../../constants/nodeAppearance.js'
import { useConfigStore } from '../../stores/configStore.js'
import { useRunStore } from '../../stores/runStore.js'
import { useUiStore } from '../../stores/uiStore.js'

const emit = defineEmits(['add'])
const configStore = useConfigStore()
const runStore = useRunStore()
const uiStore = useUiStore()
const query = ref('')
const lockReason = computed(() => runStore.running ? '正在运行，停止后可添加步骤' : configStore.saving ? '正在保存，请稍后添加步骤' : uiStore.readOnly ? '当前为只读模式，关闭只读后可添加步骤' : !configStore.selectedPreset ? '先选择或新建一个预设，再添加步骤' : '')
const locked = computed(() => Boolean(lockReason.value))
const definitions = computed(() => configStore.definitions.filter((item) => matchesStepSearch(item, query.value)))

function add(event, definition) {
  // A double-click also emits two click events. Keep its first activation only.
  if (locked.value || event.detail > 1) return
  emit('add', definition.key)
}

function dragStart(event, definition) {
  if (locked.value) return event.preventDefault()
  event.dataTransfer.effectAllowed = 'copy'
  event.dataTransfer.setData('application/x-step-kind', definition.key)
}
</script>

<template>
  <aside class="palette panel" :class="{ collapsed: uiStore.paletteCollapsed }">
    <button v-if="uiStore.paletteCollapsed" class="panel-expand-button" title="展开步骤库" aria-label="展开步骤库" @click="uiStore.paletteCollapsed = false"><PanelLeftOpen :size="17" /><Boxes :size="16" /></button>
    <template v-else>
      <div class="panel-heading">
        <div><span class="eyebrow">步骤库</span><h2>添加步骤</h2></div>
        <div class="panel-heading-actions"><span class="count">{{ definitions.length }}</span><button class="panel-collapse-button" title="收起步骤库" aria-label="收起步骤库" @click="uiStore.paletteCollapsed = true"><PanelLeftClose :size="15" /></button></div>
      </div>
      <label class="search-field">
        <Search :size="14" />
        <input v-model="query" type="search" placeholder="搜索用途，如等待、找图" aria-label="筛选步骤类型" />
        <button v-if="query" class="clear-search" title="清空搜索" aria-label="清空搜索" @click.prevent="query = ''"><X :size="13" /></button>
      </label>
      <p class="palette-help">点卡片即可添加，也可拖到画布。</p>
      <p v-if="locked" class="palette-lock" role="status">{{ lockReason }}</p>
      <div class="palette-list">
        <button v-for="definition in definitions" :key="definition.key" class="palette-item" :draggable="!locked" :disabled="locked"
          :style="{ '--item-accent': appearanceFor(definition.key).color }"
          :title="locked ? lockReason : `点击添加${definition.label}，也可双击或拖到画布`"
          :aria-label="`添加${definition.label}：${descriptionFor(definition.key)}`"
          @dragstart="dragStart($event, definition)" @click="add($event, definition)" @dblclick.prevent>
          <component :is="appearanceFor(definition.key).icon" :size="16" />
          <span><strong>{{ definition.label }}</strong><small>{{ descriptionFor(definition.key) }}</small><em><Plus :size="11" />添加步骤</em></span>
        </button>
        <div v-if="!definitions.length" class="palette-empty" role="status">
          <p>{{ query.trim() ? '没有找到合适的步骤' : '步骤库正在准备中' }}</p>
          <small>{{ query.trim() ? '试试“等待”“点击”或“找图”。' : '请稍后重试。' }}</small>
          <button v-if="query" @click="query = ''">清空搜索，查看全部</button>
        </div>
      </div>
    </template>
  </aside>
</template>

<style scoped>
.palette:not(.collapsed) { display: flex; flex-direction: column; }
.panel-heading, .search-field, .palette-help, .palette-lock { flex: none; }
.search-field { min-width: 0; }
.search-field input { min-width: 0; font-size: 11px; }
.clear-search { min-width: 20px; min-height: 20px; padding: 1px; border: 0; background: transparent; }
.palette-help, .palette-lock { margin: 3px 11px 6px; font-size: 11px; line-height: 1.6; color: var(--muted); }
.palette-lock { color: var(--amber); }
.palette-list { flex: 1; height: auto; min-height: 0; }
.palette-item { height: auto; min-height: 83px; align-items: flex-start; }
.palette-item > svg { margin-top: 3px; }
.palette-item > span { flex: 1; gap: 3px; }
.palette-item strong { white-space: normal; line-height: 1.4; }
.palette-item small { color: var(--muted); line-height: 1.5; white-space: normal; }
.palette-item em { display: inline-flex; align-items: center; gap: 3px; color: var(--item-accent); font-size: 10px; font-style: normal; }
.palette-empty { padding: 15px 6px; color: var(--muted); line-height: 1.6; }
.palette-empty p { margin: 0 0 6px; color: var(--text); }
.palette-empty small { display: block; }
.palette-empty button { margin-top: 12px; font-size: 11px; }
</style>
