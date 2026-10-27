<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { ChevronDown, ChevronUp, Eraser, Radio } from 'lucide-vue-next'
import { useRunStore } from '../../stores/runStore.js'
import { useUiStore } from '../../stores/uiStore.js'

const emit = defineEmits(['focus-node'])
const runStore = useRunStore()
const uiStore = useUiStore()
const scroller = ref(null)
const stateLabel = computed(() => runStore.running ? `运行中 · 第 ${runStore.cycle || 1} 轮 · ${runStore.stepIndex || 0}/${runStore.stepCount || 0}` : runStore.message || '等待运行')

watch(() => runStore.logs.length, async () => {
  await nextTick()
  if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
})

function time(value) {
  const date = value instanceof Date ? value : new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString('zh-CN', { hour12: false })
}
</script>

<template>
  <section class="log-panel panel" :class="{ collapsed: uiStore.logCollapsed }">
    <header>
      <div><Radio :size="15" :class="{ live: runStore.running }" /><strong>运行日志</strong><span>{{ stateLabel }}</span></div>
      <div><span class="ws-state" :class="runStore.wsState">WS {{ runStore.wsState }}</span><button class="icon-button" title="清空日志" @click="runStore.logs = []"><Eraser :size="14" /></button><button class="icon-button" :title="uiStore.logCollapsed ? '展开日志' : '折叠日志'" @click="uiStore.logCollapsed = !uiStore.logCollapsed"><ChevronUp v-if="!uiStore.logCollapsed" :size="15" /><ChevronDown v-else :size="15" /></button></div>
    </header>
    <div v-if="!uiStore.logCollapsed" ref="scroller" class="log-scroll" role="log" aria-live="polite">
      <button v-for="line in runStore.logs" :key="line.id" class="log-line" :class="line.level || line.state" :disabled="!line.step_id" @click="line.step_id && emit('focus-node', line.step_id)"><time>{{ time(line.time) }}</time><span>{{ line.text }}</span></button>
      <div v-if="!runStore.logs.length" class="log-empty">暂无运行日志</div>
    </div>
  </section>
</template>
