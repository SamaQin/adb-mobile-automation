<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { X } from 'lucide-vue-next'
import { useUiStore } from '../stores/uiStore.js'

const ui = useUiStore()
const panel = ref(null)
const input = ref(null)
const value = ref('')
let previousFocus = null
let focusVersion = 0

watch(() => ui.dialog, async (dialog) => {
  const version = ++focusVersion
  if (!dialog) {
    if (previousFocus?.isConnected) previousFocus.focus()
    previousFocus = null
    return
  }
  previousFocus ||= document.activeElement
  value.value = dialog.initialValue || ''
  await nextTick()
  if (version !== focusVersion) return
  if (dialog.kind === 'prompt') { input.value?.focus(); input.value?.select() }
  else panel.value?.querySelector('button[data-cancel]')?.focus()
}, { immediate: true })

function close(result = null) { ui.resolveDialog(result) }
function submit() {
  if (ui.dialog?.kind === 'prompt') {
    if (!value.value.trim()) return
    close(value.value.trim())
  } else close(true)
}
function keys(event) {
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close() }
  if (event.key !== 'Tab') return
  const focusable = [...panel.value.querySelectorAll('button:not(:disabled), input:not(:disabled)')]
  const first = focusable[0], last = focusable.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
onBeforeUnmount(() => { focusVersion++; if (ui.dialog) ui.resolveDialog(null) })
</script>

<template>
  <div v-if="ui.dialog" class="app-dialog-backdrop" @keydown.stop="keys" @mousedown.self="close()">
    <form ref="panel" class="app-dialog panel" role="dialog" aria-modal="true" aria-labelledby="app-dialog-title" :aria-describedby="ui.dialog.message ? 'app-dialog-message' : undefined" @submit.prevent="submit">
      <header><h2 id="app-dialog-title">{{ ui.dialog.title }}</h2><button type="button" class="icon-button" title="关闭对话框" aria-label="关闭对话框" @click="close()"><X :size="18" /></button></header>
      <p v-if="ui.dialog.message" id="app-dialog-message">{{ ui.dialog.message }}</p>
      <label v-if="ui.dialog.kind === 'prompt'" class="field"><span>{{ ui.dialog.label || '名称' }}</span><input ref="input" v-model="value" :placeholder="ui.dialog.placeholder || '请输入名称'" maxlength="160" required /></label>
      <footer><button type="button" data-cancel @click="close()">取消</button><button type="submit" :class="ui.dialog.danger ? 'danger' : 'primary'" :disabled="ui.dialog.kind === 'prompt' && !value.trim()">{{ ui.dialog.confirmLabel || '确认' }}</button></footer>
    </form>
  </div>
</template>

<style scoped>
.app-dialog-backdrop { position: fixed; inset: 0; z-index: 900; display: grid; place-items: center; background: rgba(0,0,0,.62); backdrop-filter: blur(3px); }
.app-dialog { width: min(440px, calc(100vw - 40px)); padding: 20px; background: #141f2d; }
header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
h2 { margin: 0; font-size: 17px; }
p { white-space: pre-wrap; max-height: 40vh; overflow: auto; color: var(--muted); line-height: 1.7; }
.field { margin-top: 18px; }
footer { display: flex; justify-content: flex-end; gap: 8px; margin-top: 22px; }
footer button { min-width: 74px; }
</style>
