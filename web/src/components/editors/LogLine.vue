<script setup>
import { computed } from 'vue'

const props = defineProps({ line: { type: Object, required: true } })
defineEmits(['focus-node'])
const time = computed(() => {
  const value = props.line.time
  const date = value instanceof Date ? value : new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString('zh-CN', { hour12: false })
})
</script>

<template>
  <button class="log-line" :data-log-id="line.id" :class="line.level || line.state" :disabled="!line.step_id" @click="line.step_id && $emit('focus-node', line.step_id)"><time>{{ time }}</time><span>{{ line.text }}</span></button>
</template>
