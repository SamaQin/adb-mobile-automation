<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ChevronDown, ChevronUp, Eraser, Radio } from 'lucide-vue-next'
import { useRunStore } from '../../stores/runStore.js'
import { useUiStore } from '../../stores/uiStore.js'
import LogLine from './LogLine.vue'

const emit = defineEmits(['focus-node'])
const runStore = useRunStore()
const uiStore = useUiStore()
const scroller = ref(null)
const pageVisible = ref(document.visibilityState !== 'hidden')
const visible = computed(() => !uiStore.logCollapsed && pageVisible.value)
const connectionLabel = computed(() => ({ connected: '服务已连接', connecting: '正在连接', disconnected: '连接中断，重连中' })[runStore.wsState] || '等待连接')
const following = ref(true)
async function jumpToLatest() {
  followTail = true
  following.value = true
  await nextTick()
  if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
}
const stateLabel = computed(() => runStore.running ? `运行中 · 第 ${runStore.cycle || 1} 轮 · ${runStore.stepIndex || 0}/${runStore.stepCount || 0}` : runStore.message || '等待运行')
let followTail = true
let savedPosition = null
let updateVersion = 0

function capturePosition() {
  const element = scroller.value
  if (!element) return savedPosition
  const top = element.scrollTop
  if (followTail) return { top }
  const row = [...element.children].find((child) => child.dataset.logId && child.offsetTop + child.offsetHeight > top)
  return { top, id: row?.dataset.logId, offset: row ? row.offsetTop - top : 0 }
}

function onScroll() {
  const element = scroller.value
  if (!element) return
  followTail = element.scrollHeight - element.clientHeight - element.scrollTop <= 24
  following.value = followTail
  savedPosition = capturePosition()
}

// Latest id changes even when the bounded list remains at 500. The guarded
// source does not subscribe to logs while collapsed or in a hidden document.
watch([
  () => visible.value ? runStore.logs.at(-1)?.id : null,
  visible,
], async ([, active], [, wasActive]) => {
  const version = ++updateVersion
  const position = wasActive ? capturePosition() : savedPosition
  savedPosition = position
  if (!active) return
  await nextTick()
  if (version !== updateVersion || !visible.value || !scroller.value) return
  const element = scroller.value
  if (followTail) element.scrollTop = element.scrollHeight
  else {
    const row = position?.id && [...element.children].find((child) => child.dataset.logId === position.id)
    // Stable row anchoring compensates for eviction above the viewport.
    element.scrollTop = row ? row.offsetTop - position.offset : position?.top || 0
  }
}, { immediate: true })

function onVisibilityChange() { pageVisible.value = document.visibilityState !== 'hidden' }
document.addEventListener('visibilitychange', onVisibilityChange)
onBeforeUnmount(() => {
  updateVersion++
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<template>
  <section class="log-panel panel" :class="{ collapsed: uiStore.logCollapsed }">
    <header>
      <div><Radio :size="15" :class="{ live: runStore.running }" /><strong>运行日志</strong><span>{{ stateLabel }}</span></div>
      <div><button v-if="visible && !following" class="log-latest" @click="jumpToLatest">回到最新日志</button><span class="ws-state" :class="runStore.wsState">{{ connectionLabel }}</span><button class="icon-button" title="清空日志" @click="runStore.clearLogs()"><Eraser :size="14" /></button><button class="icon-button" :title="uiStore.logCollapsed ? '展开日志' : '折叠日志'" @click="uiStore.logCollapsed = !uiStore.logCollapsed"><ChevronUp v-if="!uiStore.logCollapsed" :size="15" /><ChevronDown v-else :size="15" /></button></div>
    </header>
    <div v-if="visible" ref="scroller" class="log-scroll" role="log" aria-live="polite" @scroll="onScroll">
      <LogLine v-for="line in runStore.logs" :key="line.id" :line="line" @focus-node="emit('focus-node', $event)" />
      <div v-if="!runStore.logs.length" class="log-empty">运行后会在这里显示进度与结果。点击带步骤的日志可定位画布节点。</div>
    </div>
  </section>
</template>

<style scoped>
.log-latest { min-height:24px; padding:0 7px; font-size:11px; color:var(--cyan); }
.log-scroll {
  position: relative;
  overflow-anchor: none;
}
</style>
