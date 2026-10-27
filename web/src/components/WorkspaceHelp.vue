<script setup>
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { X } from 'lucide-vue-next'
import { useUiStore } from '../stores/uiStore.js'
const ui = useUiStore()
const panel = ref(null)
let previous
onMounted(() => { previous = document.activeElement; panel.value?.querySelector('button')?.focus() })
onBeforeUnmount(() => { if (previous?.isConnected) previous.focus() })
function keys(event) {
  if (event.key === 'Escape') { event.preventDefault(); ui.helpOpen = false }
  if (event.key === 'Tab') { event.preventDefault(); panel.value?.querySelector('button')?.focus() }
}
</script>
<template>
  <div class="help-backdrop" @mousedown.self="ui.helpOpen = false" @keydown.stop="keys">
    <section ref="panel" class="help-dialog panel" role="dialog" aria-modal="true" aria-labelledby="help-title">
      <header><h2 id="help-title">快速上手</h2><button class="icon-button" title="关闭帮助" aria-label="关闭帮助" @click="ui.helpOpen = false"><X :size="18" /></button></header>
      <ol class="help-steps">
        <li><strong>添加步骤</strong><p>在左侧点击添加按钮，或将步骤拖入画布。选中节点后，在右侧设置参数。</p></li>
        <li><strong>准备识别与坐标</strong><p>识别步骤需要先选择模板。坐标和搜索区域可通过截图按钮直接选取，保存的是设备原始像素。</p></li>
        <li><strong>运行并查看结果</strong><p>连接已授权的 Android 设备，点击运行。修改会在运行前保存；可随时请求停止，并从日志定位步骤。</p></li>
      </ol>
      <div class="help-connections"><h3>连接线表示什么</h3><p><b>顺序：</b>按步骤列表依次执行。<b>前置依赖：</b>前置步骤未成功时，本轮跳过后续步骤。</p><p><b>模板分支：</b>命中对应模板后执行分支。<b>返回：</b>执行后回到指定的前面步骤。</p></div>
      <div class="help-shortcuts"><span><kbd>Ctrl / ⌘ + S</kbd> 保存</span><span><kbd>Ctrl / ⌘ + Z</kbd> 撤销</span><span><kbd>Ctrl / ⌘ + Shift + Z</kbd> 重做</span><span><kbd>Shift + 点击</kbd> 多选</span><span><kbd>Delete</kbd> 删除选中内容</span><span><kbd>Esc</kbd> 关闭菜单或弹窗</span></div>
      <p class="help-note">拖动节点只改变画布位置。需要改变执行先后时，使用属性面板的上移、下移，或“按布局重排执行顺序”。循环次数为 0 时持续运行，直到停止或失败。</p>
    </section>
  </div>
</template>
<style scoped>
.help-backdrop { position:fixed; inset:0; z-index:850; background:rgba(0,0,0,.62); display:grid; place-items:center; backdrop-filter:blur(3px); }
.help-dialog { width:min(640px,calc(100vw - 40px)); max-height:calc(100vh - 50px); overflow:auto; padding:22px; background:#141f2d; }
header { display:flex; align-items:center; justify-content:space-between; } h2 { margin:0; font-size:19px; } h3 { font-size:13px; color:var(--text); margin:0 0 8px; }
.help-steps { padding-left:24px; margin:20px 0; } li { padding-left:5px; margin:12px 0; } p { color:var(--muted); line-height:1.7; margin:5px 0; }
.help-connections { padding:14px; border:1px solid var(--line); border-radius:8px; } b { color:var(--text); }
.help-shortcuts { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin:18px 0; font-size:12px; color:var(--muted); } kbd { display:inline-block; border:1px solid var(--line); background:var(--control); border-radius:4px; padding:3px 5px; margin-right:5px; color:var(--text); font-size:11px; }
.help-note { border-top:1px solid var(--line); padding-top:12px; font-size:12px; }
</style>
