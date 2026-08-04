<script setup>
import { ref } from 'vue'
import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-vue-next'
import { useConfigStore } from '../../stores/configStore.js'

const props = defineProps({ nodeId: String, step: Object, disabled: Boolean })
const configStore = useConfigStore()
const choices = ref({})

function add(index) {
  const kind = choices.value[index] || configStore.definitions[0]?.key
  if (kind) configStore.addBranchStep(props.nodeId, index, kind)
}
</script>

<template>
  <section class="form-section branch-editor">
    <div class="section-title"><span>模板分支</span><small>一层展开</small></div>
    <div v-for="(template, index) in step.params?.templates || []" :key="template.file" class="branch-group">
      <header><strong>分支 {{ index + 1 }}</strong><span :title="template.file">{{ template.file }}</span></header>
      <div v-if="step.params?.branches?.[String(index)]?.length" class="branch-step-list">
        <div v-for="(child, childIndex) in step.params.branches[String(index)]" :key="child.id" class="branch-step-row">
          <span>{{ childIndex + 1 }}</span><strong>{{ child.name }}</strong>
          <button class="icon-button" title="上移" :disabled="disabled || childIndex === 0" @click="configStore.moveStep(`branch:${step.id}:${index}:${child.id}`, -1)"><ArrowUp :size="13" /></button>
          <button class="icon-button" title="下移" :disabled="disabled || childIndex === step.params.branches[String(index)].length - 1" @click="configStore.moveStep(`branch:${step.id}:${index}:${child.id}`, 1)"><ArrowDown :size="13" /></button>
          <button class="icon-button danger" title="删除分支步骤" :disabled="disabled" @click="configStore.deleteSteps([`branch:${step.id}:${index}:${child.id}`])"><Trash2 :size="13" /></button>
        </div>
      </div>
      <div class="branch-add-row">
        <select v-model="choices[index]" :disabled="disabled"><option value="">选择步骤类型</option><option v-for="definition in configStore.definitions" :key="definition.key" :value="definition.key">{{ definition.label }}</option></select>
        <button class="icon-button" title="添加分支步骤" :disabled="disabled" @click="add(index)"><Plus :size="15" /></button>
        <button v-if="step.params?.branches?.[String(index)]" class="icon-button danger" title="清空分支" :disabled="disabled" @click="configStore.removeBranch(nodeId, index)"><Trash2 :size="14" /></button>
      </div>
    </div>
    <p v-if="!(step.params?.templates || []).length" class="empty-copy">选择模板后可配置命中分支。</p>
  </section>
</template>
