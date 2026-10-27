import { defineStore } from 'pinia'
import {
  duplicatePreset as duplicatePresetApi,
  fetchConfig,
  fetchPresetReferences,
  fetchStepDefinitions,
  saveConfig,
  setAcceleration as setAccelerationApi,
} from '../api/config.js'
import { normalizeDependencies, parseBranchNodeId } from '../flow/createFlow.js'
import { cloneJson } from '../utils/clone.js'
import { useHistoryStore } from './historyStore.js'

const clone = cloneJson
const newId = () => (globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`).replaceAll('-', '')

function remapStep(step, idMap = new Map()) {
  const copy = clone(step)
  const oldId = copy.id
  copy.id = newId()
  idMap.set(oldId, copy.id)
  const branches = copy.params?.branches || {}
  for (const branchSteps of Object.values(branches)) {
    for (let i = 0; i < branchSteps.length; i += 1) branchSteps[i] = remapStep(branchSteps[i], idMap)
  }
  return copy
}

function applyRemappedDependencies(step, idMap) {
  step.depends_on = (step.depends_on || []).map((id) => idMap.get(id) || id).filter((id) => id !== step.id)
  if (step.params?.return_to) step.params.return_to = idMap.get(step.params.return_to) || step.params.return_to
  for (const branchSteps of Object.values(step.params?.branches || {})) {
    branchSteps.forEach((child) => applyRemappedDependencies(child, idMap))
  }
}

export const useConfigStore = defineStore('config', {
  state: () => ({ config: null, definitions: [], loading: false, saving: false, dirty: false, error: '' }),
  getters: {
    presets: (state) => state.config?.presets || [],
    selectedPreset(state) {
      return state.config?.presets?.find((preset) => preset.id === state.config.selected_preset_id) || state.config?.presets?.[0] || null
    },
    definitionMap: (state) => new Map(state.definitions.map((item) => [item.key, item])),
  },
  actions: {
    snapshot() {
      return clone(this.config)
    },
    record(label) {
      if (this.config) useHistoryStore().push(this.snapshot(), label)
    },
    changed() {
      this.dirty = true
    },
    async load() {
      this.loading = true
      this.error = ''
      try {
        const [config, definitions] = await Promise.all([fetchConfig(), fetchStepDefinitions()])
        this.config = config
        this.definitions = definitions
        this.dirty = false
        useHistoryStore().clear()
      } catch (error) {
        this.error = error.message
        throw error
      } finally {
        this.loading = false
      }
    },
    async save() {
      if (!this.config) return
      this.saving = true
      try {
        const result = await saveConfig(this.config)
        if (result?.presets) this.config = result
        this.dirty = false
        useHistoryStore().clear()
      } finally {
        this.saving = false
      }
    },
    replaceFromHistory(snapshot) {
      this.config = clone(snapshot)
      this.dirty = true
    },
    selectPreset(id) {
      if (!this.config?.presets.some((preset) => preset.id === id)) return
      this.config.selected_preset_id = id
      this.changed()
    },
    addPreset(name) {
      const clean = name.trim()
      if (!clean) throw new Error('预设名称不能为空')
      if (this.presets.some((preset) => preset.name === clean)) throw new Error('已有同名预设')
      this.record('新建预设')
      const preset = { id: newId(), name: clean, loop_count: 1, steps: [] }
      this.config.presets.push(preset)
      this.config.selected_preset_id = preset.id
      this.changed()
      return preset
    },
    async duplicatePreset(presetId) {
      this.record('复制预设')
      try {
        const result = await duplicatePresetApi(presetId)
        if (result?.presets) {
          this.config = result
          this.changed()
          return this.selectedPreset
        }
        if (result?.id) {
          this.config.presets.push(result)
          this.config.selected_preset_id = result.id
          this.changed()
          return result
        }
      } catch (error) {
        if (error.status !== 404 && error.status !== 405) throw error
      }
      const source = this.presets.find((item) => item.id === presetId)
      if (!source) throw new Error('未找到预设')
      const idMap = new Map()
      const copy = clone(source)
      copy.id = newId()
      copy.name = this.uniquePresetName(`${source.name} 副本`)
      copy.steps = copy.steps.map((step) => remapStep(step, idMap))
      copy.steps.forEach((step) => applyRemappedDependencies(step, idMap))
      this.config.presets.push(copy)
      this.config.selected_preset_id = copy.id
      this.changed()
      return copy
    },
    uniquePresetName(base) {
      let name = base
      let index = 2
      while (this.presets.some((preset) => preset.name === name)) name = `${base} ${index++}`
      return name
    },
    renamePreset(id, name) {
      const clean = name.trim()
      if (!clean) throw new Error('预设名称不能为空')
      if (this.presets.some((preset) => preset.id !== id && preset.name === clean)) throw new Error('已有同名预设')
      const preset = this.presets.find((item) => item.id === id)
      if (!preset || preset.name === clean) return
      this.record('重命名预设')
      preset.name = clean
      this.changed()
    },
    async referencesForPreset(id) {
      try {
        return await fetchPresetReferences(id)
      } catch (error) {
        if (error.status !== 404 && error.status !== 405) throw error
        const references = []
        const scan = (steps, presetName) => {
          for (const step of steps || []) {
            if (step.kind === 'run_preset' && step.params?.preset_id === id) references.push({ preset_name: presetName, step_name: step.name })
            Object.values(step.params?.branches || {}).forEach((branch) => scan(branch, presetName))
          }
        }
        this.presets.forEach((preset) => scan(preset.steps, preset.name))
        return references
      }
    },
    deletePreset(id) {
      if (this.presets.length <= 1) throw new Error('配置中至少需要一个预设')
      this.record('删除预设')
      this.config.presets = this.presets.filter((preset) => preset.id !== id)
      if (this.config.selected_preset_id === id) this.config.selected_preset_id = this.config.presets[0].id
      this.changed()
    },
    setLoopCount(value) {
      const number = Number(value)
      if (!Number.isInteger(number) || number < 0) throw new Error('循环次数必须是非负整数')
      if (this.selectedPreset.loop_count === number) return
      this.record('修改循环次数')
      this.selectedPreset.loop_count = number
      this.changed()
    },
    async setAcceleration(value) {
      const previous = this.config.acceleration
      this.record('修改加速模式')
      this.config.acceleration = value
      this.changed()
      try {
        const result = await setAccelerationApi(value)
        if (typeof result === 'string') this.config.acceleration = result
        else if (result?.acceleration) this.config.acceleration = result.acceleration
      } catch (error) {
        this.config.acceleration = previous
        throw error
      }
    },
    createStep(kind) {
      const def = this.definitionMap.get(kind)
      const params = Object.fromEntries((def?.fields || []).map((field) => [field.key, clone(field.default)]))
      return {
        id: newId(),
        name: def?.label || kind,
        kind,
        enabled: true,
        on_failure: 'stop',
        depends_on: [],
        params,
      }
    },
    addStep(kind, afterId = null) {
      const step = this.createStep(kind)
      this.record('新增步骤')
      const index = afterId ? this.selectedPreset.steps.findIndex((item) => item.id === afterId) + 1 : this.selectedPreset.steps.length
      this.selectedPreset.steps.splice(Math.max(0, index), 0, step)
      normalizeDependencies(this.selectedPreset.steps)
      this.changed()
      return step
    },
    findStep(nodeId) {
      const branch = parseBranchNodeId(nodeId)
      if (!branch) return { step: this.selectedPreset?.steps.find((item) => item.id === nodeId), list: this.selectedPreset?.steps, branch: null }
      const parent = findStepRecursive(this.selectedPreset?.steps || [], branch.parentStepId)?.step
      const list = parent?.params?.branches?.[branch.index]
      return { step: list?.find((item) => item.id === branch.stepId), list, parent, branch }
    },
    mutateStep(nodeId, mutator, label = '编辑步骤') {
      const found = this.findStep(nodeId)
      if (!found.step) return
      this.record(label)
      mutator(found.step, found)
      if (found.list) normalizeDependencies(this.selectedPreset.steps)
      this.changed()
    },
    deleteSteps(nodeIds) {
      const ids = new Set(nodeIds)
      if (!ids.size) return
      this.record('删除步骤')
      this.selectedPreset.steps = this.selectedPreset.steps.filter((step) => !ids.has(step.id))
      this.selectedPreset.steps.forEach((step) => removeBranchStepsRecursive(step, ids))
      normalizeDependencies(this.selectedPreset.steps)
      this.changed()
    },
    duplicateStep(nodeId) {
      const found = this.findStep(nodeId)
      if (!found.step || !found.list) return null
      this.record('复制步骤')
      const idMap = new Map()
      const copy = remapStep(found.step, idMap)
      applyRemappedDependencies(copy, idMap)
      copy.name = `${copy.name} 副本`
      const index = found.list.indexOf(found.step)
      found.list.splice(index + 1, 0, copy)
      normalizeDependencies(this.selectedPreset.steps)
      this.changed()
      return found.branch ? `branch:${found.branch.parentStepId}:${found.branch.index}:${copy.id}` : copy.id
    },
    duplicateSteps(nodeIds) {
      const selected = new Set(nodeIds)
      const main = this.selectedPreset.steps.filter((step) => selected.has(step.id))
      if (!main.length) {
        const copies = nodeIds.map((id) => this.duplicateStep(id)).filter(Boolean)
        return copies
      }
      this.record('复制步骤')
      const idMap = new Map()
      const copies = main.map((step) => remapStep(step, idMap))
      copies.forEach((step) => applyRemappedDependencies(step, idMap))
      copies.forEach((step) => { step.name = `${step.name} 副本` })
      const insertAt = Math.max(...main.map((step) => this.selectedPreset.steps.indexOf(step))) + 1
      this.selectedPreset.steps.splice(insertAt, 0, ...copies)
      normalizeDependencies(this.selectedPreset.steps)
      this.changed()
      return copies.map((step) => step.id)
    },
    moveStep(nodeId, delta) {
      const found = this.findStep(nodeId)
      if (!found.step || !found.list) return
      const from = found.list.indexOf(found.step)
      const to = from + delta
      if (to < 0 || to >= found.list.length) return
      this.record(delta < 0 ? '上移步骤' : '下移步骤')
      found.list.splice(to, 0, found.list.splice(from, 1)[0])
      normalizeDependencies(this.selectedPreset.steps)
      this.changed()
    },
    reorderSteps(orderedIds) {
      const map = new Map(this.selectedPreset.steps.map((step) => [step.id, step]))
      const next = orderedIds.map((id) => map.get(id)).filter(Boolean)
      if (next.length !== this.selectedPreset.steps.length) return
      this.record('按布局重排')
      this.selectedPreset.steps = next
      normalizeDependencies(this.selectedPreset.steps)
      this.changed()
    },
    connectOrder(sourceId, targetId) {
      const target = this.findStep(targetId)
      if (!target.step || !target.list) throw new Error('找不到顺序连接的目标步骤')
      if (target.step.depends_on?.length) throw new Error('特殊依赖步骤不能加入默认顺序链')

      let insertAt = 0
      if (sourceId !== 'start') {
        const source = this.findStep(sourceId)
        if (!source.step || source.list !== target.list) throw new Error('顺序连接必须位于同一流程')
        if (source.step.depends_on?.length) throw new Error('特殊依赖步骤不能作为默认顺序出口')
        insertAt = source.list.indexOf(source.step) + 1
      } else if (target.branch) {
        throw new Error('开始节点只能连接主流程步骤')
      }

      const from = target.list.indexOf(target.step)
      const currentPrevious = from > 0 ? target.list[from - 1] : null
      if ((sourceId === 'start' && from === 0) || currentPrevious?.id === sourceId) return false
      this.record('调整执行顺序')
      target.list.splice(from, 1)
      if (from < insertAt) insertAt -= 1
      while (insertAt < target.list.length && target.list[insertAt].depends_on?.length) insertAt += 1
      target.list.splice(insertAt, 0, target.step)
      normalizeDependencies(this.selectedPreset.steps)
      this.changed()
      return true
    },
    connectBranch(sourceId, branchIndex, targetId) {
      const source = this.findStep(sourceId)
      const target = this.findStep(targetId)
      if (!source.step || !target.step || !target.list || !target.branch) throw new Error('分支连接端点无效')
      if (target.branch.parentStepId !== source.step.id || target.branch.index !== String(branchIndex)) {
        throw new Error('模板分支只能连接自身分支内的步骤')
      }
      if (target.step.depends_on?.length) throw new Error('分支入口不能连接带前置依赖的步骤')
      const from = target.list.indexOf(target.step)
      if (from === 0) return false
      this.record('调整分支入口')
      target.list.splice(from, 1)
      target.list.unshift(target.step)
      normalizeDependencies(this.selectedPreset.steps)
      this.changed()
      return true
    },
    addDependency(sourceId, targetId) {
      this.mutateStep(targetId, (step) => {
        step.depends_on = [...new Set([...(step.depends_on || []), parseBranchNodeId(sourceId)?.stepId || sourceId])]
      }, '新增依赖')
    },
    removeDependency(sourceId, targetId) {
      this.mutateStep(targetId, (step) => {
        const source = parseBranchNodeId(sourceId)?.stepId || sourceId
        step.depends_on = (step.depends_on || []).filter((id) => id !== source)
      }, '删除依赖')
    },
    connectReturn(sourceId, targetId) {
      const found = this.findStep(sourceId)
      if (!found.step) throw new Error('找不到返回连接的来源步骤')
      const target = parseBranchNodeId(targetId)?.stepId || targetId
      if (found.step.params?.return_to === target) return false
      this.record('添加返回连接')
      found.step.params ||= {}
      found.step.params.return_to = target
      if (found.list) normalizeDependencies(this.selectedPreset.steps)
      this.changed()
      return true
    },
    removeReturn(sourceId) {
      const found = this.findStep(sourceId)
      if (!found.step?.params?.return_to) return
      this.record('删除返回连接')
      delete found.step.params.return_to
      this.changed()
    },
    addBranchStep(parentNodeId, branchIndex, kind) {
      const found = this.findStep(parentNodeId)
      if (!found.step) return null
      const child = this.createStep(kind)
      this.record('新增分支步骤')
      found.step.params ||= {}
      found.step.params.branches ||= {}
      found.step.params.branches[String(branchIndex)] ||= []
      found.step.params.branches[String(branchIndex)].push(child)
      this.changed()
      return `branch:${found.step.id}:${branchIndex}:${child.id}`
    },
    removeBranch(parentNodeId, branchIndex) {
      const found = this.findStep(parentNodeId)
      if (!found.step?.params?.branches?.[String(branchIndex)]) return
      this.record('清空分支')
      delete found.step.params.branches[String(branchIndex)]
      this.changed()
    },
    updateTemplates(nodeId, templates) {
      const found = this.findStep(nodeId)
      if (!found.step) return
      this.record('修改识别模板')
      const oldTemplates = found.step.params?.templates || []
      const oldBranches = found.step.params?.branches || {}
      const branchesByFile = new Map(oldTemplates.map((template, index) => [template.file, oldBranches[String(index)]]))
      found.step.params ||= {}
      found.step.params.templates = clone(templates)
      const nextBranches = {}
      templates.forEach((template, index) => {
        const branch = branchesByFile.get(template.file)
        if (branch?.length) nextBranches[String(index)] = branch
      })
      if (Object.keys(nextBranches).length) found.step.params.branches = nextBranches
      else delete found.step.params.branches
      this.changed()
    },
    updateTemplateResolution(file, resolution) {
      let changed = false
      const walk = (steps) => {
        for (const step of steps || []) {
          for (const template of step.params?.templates || []) {
            if (template.file === file) {
              template.screen_resolution = clone(resolution)
              changed = true
            }
          }
          Object.values(step.params?.branches || {}).forEach(walk)
        }
      }
      this.config?.presets?.forEach((preset) => walk(preset.steps))
      if (changed) this.changed()
    },
    applyScreenResolution(resolution) {
      const walk = (steps) => {
        for (const step of steps || []) {
          const def = this.definitionMap.get(step.kind)
          if ((def?.fields || []).some((field) => field.coordinate_axis) && !step.screen_resolution) {
            step.screen_resolution = clone(resolution)
          }
          for (const template of step.params?.templates || []) {
            if (!template.screen_resolution) template.screen_resolution = clone(resolution)
          }
          Object.values(step.params?.branches || {}).forEach(walk)
        }
      }
      walk(this.config?.presets?.flatMap((preset) => preset.steps) || [])
    },
    replacePreset(preset) {
      const index = this.presets.findIndex((item) => item.id === this.selectedPreset.id)
      this.record('导入画布')
      this.config.presets[index] = clone(preset)
      this.config.selected_preset_id = preset.id
      this.changed()
    },
  },
})

function branchNodeIdSafe(parentId, index, stepId) {
  return `branch:${parentId}:${index}:${stepId}`
}

function findStepRecursive(steps, id) {
  for (const step of steps || []) {
    if (step.id === id) return { step, list: steps }
    for (const branchSteps of Object.values(step.params?.branches || {})) {
      const found = findStepRecursive(branchSteps, id)
      if (found) return found
    }
  }
  return null
}

function removeBranchStepsRecursive(parent, ids) {
  for (const [index, branchSteps] of Object.entries(parent.params?.branches || {})) {
    parent.params.branches[index] = branchSteps.filter((step) => !ids.has(branchNodeIdSafe(parent.id, index, step.id)))
    parent.params.branches[index].forEach((step) => removeBranchStepsRecursive(step, ids))
  }
}
