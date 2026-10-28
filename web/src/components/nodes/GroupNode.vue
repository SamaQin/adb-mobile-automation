<script setup>
import { computed } from 'vue'
import { Columns3, Trash2 } from 'lucide-vue-next'
import { useConfigStore } from '../../stores/configStore.js'
import { useLayoutStore } from '../../stores/layoutStore.js'
import { useRunStore } from '../../stores/runStore.js'
import { useUiStore } from '../../stores/uiStore.js'

const props = defineProps({ id: String, data: Object })
const configStore = useConfigStore()
const layoutStore = useLayoutStore()
const runStore = useRunStore()
const uiStore = useUiStore()
const locked = computed(() => uiStore.readOnly || runStore.running || runStore.preparing || configStore.saving)

function remove() {
  if (locked.value) return
  layoutStore.removeGroup(configStore.selectedPreset.id, props.id)
}
</script>

<template>
  <section class="group-node" :style="{ '--group-accent': data.group.color }">
    <header>
      <Columns3 :size="15" />
      <strong :title="data.group.name">{{ data.group.name }}</strong>
      <span>{{ data.memberCount }} 个步骤</span>
      <button class="icon-button nodrag danger" title="删除泳道" :disabled="locked" @click.stop="remove"><Trash2 :size="13" /></button>
    </header>
  </section>
</template>
