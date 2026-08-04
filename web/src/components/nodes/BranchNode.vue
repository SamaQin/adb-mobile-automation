<script setup>
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { Check, Copy, GitBranch, Power, Trash2, X } from 'lucide-vue-next'
import { appearanceFor } from '../../constants/nodeAppearance.js'
import { useConfigStore } from '../../stores/configStore.js'
import { useRunStore } from '../../stores/runStore.js'
import { useUiStore } from '../../stores/uiStore.js'

const props = defineProps({ id: String, data: Object, selected: Boolean })
const configStore = useConfigStore()
const runStore = useRunStore()
const uiStore = useUiStore()
const appearance = computed(() => appearanceFor(props.data.step?.kind))
const Icon = computed(() => appearance.value.icon)
const locked = computed(() => uiStore.readOnly || runStore.running || configStore.saving)
const nestedBranchCount = computed(() => Object.values(props.data.step?.params?.branches || {}).reduce((count, steps) => count + (steps?.length || 0), 0))
</script>

<template>
  <div class="step-node branch-node" :class="[`state-${data.state || 'idle'}`, { selected, disabled: !data.step.enabled }]" :style="{ '--node-accent': appearance.color }">
    <Handle id="order-target" type="target" :position="Position.Top" :connectable="!locked" />
    <div class="node-accent" />
    <div v-if="!locked" class="node-actions nodrag">
      <button title="复制分支步骤" :disabled="locked" @click.stop="configStore.duplicateStep(id)"><Copy :size="13" /></button>
      <button :title="data.step.enabled ? '停用步骤' : '启用步骤'" :disabled="locked" @click.stop="configStore.mutateStep(id, (step) => { step.enabled = !step.enabled }, '切换步骤')"><Power :size="13" /></button>
      <button title="删除分支步骤" class="danger" :disabled="locked" @click.stop="configStore.deleteSteps([id])"><Trash2 :size="13" /></button>
    </div>
    <header>
      <span class="node-order">{{ data.order }}</span>
      <component :is="Icon" :size="15" />
      <strong :title="data.step.name">{{ data.step.name }}</strong>
      <Check v-if="data.state === 'done'" :size="15" class="state-icon success" />
      <X v-if="data.state === 'failed'" :size="15" class="state-icon failure" />
    </header>
    <div class="node-meta"><span>{{ data.def?.label || data.step.kind }}</span><span v-if="nestedBranchCount" class="badge branch"><GitBranch :size="10" />分支 {{ nestedBranchCount }} 步</span><span v-if="data.returnTargetName" class="badge return" :title="`执行后回到：${data.returnTargetName}`">↺返回</span></div>
    <p>{{ data.step.kind === 'wait' ? `${data.step.params?.seconds ?? 1} 秒` : data.step.params?.templates?.[0]?.file || '分支步骤' }}</p>
    <footer title="分支来源"><GitBranch :size="12" /> 来自：{{ data.branch.label }} · 分支 {{ Number(data.branch.index) + 1 }}</footer>
    <Handle id="order-source" type="source" :position="Position.Bottom" :connectable="!locked" />
    <Handle
      id="dependency-source"
      type="source"
      :position="Position.Right"
      :connectable="!locked"
      class="dependency-handle"
      :class="{ 'dependency-handle-add': !data.outgoingDependencyCount }"
    />
  </div>
</template>
