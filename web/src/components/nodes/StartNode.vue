<script setup>
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { Play } from 'lucide-vue-next'
import { useConfigStore } from '../../stores/configStore.js'
import { useRunStore } from '../../stores/runStore.js'
import { useUiStore } from '../../stores/uiStore.js'

defineProps({ data: { type: Object, required: true } })
const configStore = useConfigStore()
const runStore = useRunStore()
const uiStore = useUiStore()
const locked = computed(() => uiStore.readOnly || runStore.running || runStore.preparing || configStore.saving)
</script>

<template>
  <div class="start-node" title="执行顺序入口">
    <Play :size="18" fill="currentColor" />
    <span>开始</span>
    <small>{{ data.label }}</small>
    <Handle id="order-source" type="source" :position="Position.Bottom" :connectable="!locked" />
  </div>
</template>
