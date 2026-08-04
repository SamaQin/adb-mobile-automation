<script setup>
import { computed, ref } from 'vue'
import { Boxes, PanelLeftClose, PanelLeftOpen, Search } from 'lucide-vue-next'
import { appearanceFor } from '../../constants/nodeAppearance.js'
import { useConfigStore } from '../../stores/configStore.js'
import { useRunStore } from '../../stores/runStore.js'
import { useUiStore } from '../../stores/uiStore.js'

const emit = defineEmits(['add'])
const configStore = useConfigStore()
const runStore = useRunStore()
const uiStore = useUiStore()
const query = ref('')
const locked = computed(() => uiStore.readOnly || runStore.running || configStore.saving)
const definitions = computed(() => configStore.definitions.filter((item) => `${item.label} ${item.key}`.toLowerCase().includes(query.value.toLowerCase())))

function dragStart(event, definition) {
  if (locked.value) return event.preventDefault()
  event.dataTransfer.effectAllowed = 'copy'
  event.dataTransfer.setData('application/x-step-kind', definition.key)
}
</script>

<template>
  <aside class="palette panel" :class="{ collapsed: uiStore.paletteCollapsed }">
    <button
      v-if="uiStore.paletteCollapsed"
      class="panel-expand-button"
      title="展开节点库"
      aria-label="展开节点库"
      @click="uiStore.paletteCollapsed = false"
    ><PanelLeftOpen :size="17" /><Boxes :size="16" /></button>
    <template v-else>
    <div class="panel-heading">
      <div><span class="eyebrow">节点库</span><h2>步骤类型</h2></div>
      <div class="panel-heading-actions"><span class="count">{{ definitions.length }}</span><button class="panel-collapse-button" title="收起节点库" aria-label="收起节点库" @click="uiStore.paletteCollapsed = true"><PanelLeftClose :size="15" /></button></div>
    </div>
    <label class="search-field">
      <Search :size="14" />
      <input v-model="query" type="search" placeholder="筛选步骤" aria-label="筛选步骤类型" />
    </label>
    <div class="palette-list">
      <button
        v-for="definition in definitions"
        :key="definition.key"
        class="palette-item"
        draggable="true"
        :disabled="locked"
        :style="{ '--item-accent': appearanceFor(definition.key).color }"
        :title="`双击或拖入画布添加${definition.label}`"
        @dragstart="dragStart($event, definition)"
        @dblclick="emit('add', definition.key)"
      >
        <component :is="appearanceFor(definition.key).icon" :size="16" />
        <span><strong>{{ definition.label }}</strong><small>{{ definition.fields.length }} 个参数</small></span>
      </button>
    </div>
    </template>
  </aside>
</template>
