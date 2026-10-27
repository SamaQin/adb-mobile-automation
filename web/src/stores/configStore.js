import { defineStore } from 'pinia'
import {
  fetchConfig,
  fetchPresetReferences,
  fetchStepDefinitions,
  saveConfig,
  setAcceleration as setAccelerationApi,
} from '../api/config.js'
import { normalizeDependencies, parseBranchNodeId } from '../flow/createFlow.js'
import { cloneJson } from '../utils/clone.js'
import { useHistoryStore } from './historyStore.js'
import { useLayoutStore } from './layoutStore.js'

const pendingSaves = new WeakMap()

const clone = cloneJson
const newId = () => (globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`).replaceAll('-', '')

function remapStep(step, idMap = new Map()) {
  const copy = clone(step)
  const remap = (item) => {
    const oldId = item.id
    item.id = newId()
    idMap.set(oldId, item.id)
    for (const children of Object.values(item.params?.branches || {})) children.forEach(remap)
  }
  remap(copy)
  return copy
}

// Reuse unchanged draft fields so editing a name does not replace params,
// branches, or dependencies observed by the canvas.
function shareUnchanged(previous, next) {
  if (previous === next) return previous
  if (!previous || !next || typeof previous !== 'object' || typeof next !== 'object'
    || Array.isArray(previous) !== Array.isArray(next)) return next
  const keys = Object.keys(next)
  let same = keys.length === Object.keys(previous).length
  for (const key of keys) {
    next[key] = shareUnchanged(previous[key], next[key])
    if (!(key in previous) || previous[key] !== next[key]) same = false
  }
  return same ? previous : next
}

function dependencyStructureChanged(previous, next) {
  if (previous === next) return false
  if (previous.id !== next.id || previous.depends_on !== next.depends_on
    || previous.params?.return_to !== next.params?.return_to) return true
  const before = previous.params?.branches || {}
  const after = next.params?.branches || {}
  if (before === after) return false
  const keys = Object.keys(after)
  if (keys.length !== Object.keys(before).length) return true
  return keys.some((key) => !before[key] || before[key].length !== after[key].length
    || after[key].some((step, index) => dependencyStructureChanged(before[key][index], step)))
}

function selectedRoots(steps, selected, parent = null, branchIndex = null) {
  const found = []
  for (const step of steps || []) {
    const nodeId = parent ? branchNodeIdSafe(parent.id, branchIndex, step.id) : step.id
    if (selected.has(nodeId)) found.push({ step, list: steps, nodeId, parent, branchIndex })
    else {
      for (const [index, children] of Object.entries(step.params?.branches || {})) {
        found.push(...selectedRoots(children, selected, step, index))
      }
    }
  }
  return found
}

function applyRemappedDependencies(step, idMap) {
  step.depends_on = (step.depends_on || []).map((id) => idMap.get(id) || id).filter((id) => id !== step.id)
  if (step.params?.return_to) step.params.return_to = idMap.get(step.params.return_to) || step.params.return_to
  for (const branchSteps of Object.values(step.params?.branches || {})) {
    branchSteps.forEach((child) => applyRemappedDependencies(child, idMap))
  }
}

export const useConfigStore = defineStore('config', {
  state: () => ({ config: null, definitions: [], loading: false, saving: false, dirty: false, error: '', revision: 0, savedConfig: '' }),
  getters: {
    presets: (state) => state.config?.presets || [],
    selectedPreset(state) {
      return state.config?.presets?.find((preset) => preset.id === state.config.selected_preset_id) || state.config?.presets?.[0] || null
    },
    definitionMap: (state) => new Map(state.definitions.map((item) => [item.key, item])),
  },
  actions: {
    snapshot() {
      return { config: clone(this.config), layouts: clone(useLayoutStore().layouts) }
    },
    record(label) {
      if (this.config) useHistoryStore().push({ config: this.config, layouts: useLayoutStore().layouts }, label)
    },
    changed() {
      this.revision += 1
      this.dirty = true
    },
    async load() {
      this.loading = true
      this.error = ''
      const revision = this.revision
      try {
        const [config, definitions] = await Promise.all([fetchConfig(), fetchStepDefinitions()])
        if (this.revision !== revision) return
        this.config = config
        this.definitions = definitions
        this.dirty = false
        this.savedConfig = JSON.stringify(config)
        this.revision += 1
        useHistoryStore().clear()
      } catch (error) {
        this.error = error.message
        throw error
      } finally {
        this.loading = false
      }
    },
    save() {
      if (!this.config) return Promise.resolve()
      if (pendingSaves.has(this)) return pendingSaves.get(this)
      if (this.saving) return Promise.reject(new Error('设置正在保存，请稍后重试'))
      const payload = clone(this.config)
      const revision = this.revision
      const serialized = JSON.stringify(payload)
      this.saving = true
      const request = Promise.resolve().then(() => saveConfig(payload)).then((result) => {
        this.savedConfig = JSON.stringify(result?.presets ? result : payload)
        // A delayed response must never overwrite edits made after this request.
        if (this.revision === revision && JSON.stringify(this.config) === serialized) {
          if (result?.presets) this.config = result
          this.dirty = false
        } else {
          this.dirty = JSON.stringify(this.config) !== this.savedConfig
        }
        return result
      }).finally(() => {
        pendingSaves.delete(this)
        this.saving = false
      })
      pendingSaves.set(this, request)
      return request
    },
    replaceFromHistory(snapshot) {
      this.config = clone(snapshot.config ?? snapshot)
      if (snapshot.layouts) useLayoutStore().restore(snapshot.layouts)
      this.revision += 1
      this.dirty = JSON.stringify(this.config) !== this.savedConfig
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
      // Duplicate the current draft, including unsaved edits, in one undoable operation.
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
      if (this.saving || this.config.acceleration === value) return
      const previous = this.config.acceleration
      this.record('修改加速模式')
      this.config.acceleration = value
      this.changed()
      const revision = this.revision
      this.saving = true
      try {
        const result = await setAccelerationApi(value)
        const applied = typeof result === 'string' ? result : result?.acceleration || value
        if (this.revision === revision) this.config.acceleration = applied
        // This endpoint persists the setting independently of the draft config.
        if (this.savedConfig) {
          const baseline = JSON.parse(this.savedConfig)
          baseline.acceleration = applied
          this.savedConfig = JSON.stringify(baseline)
          this.dirty = JSON.stringify(this.config) !== this.savedConfig
        }
      } catch (error) {
        if (this.revision === revision) this.config.acceleration = previous
        this.dirty = JSON.stringify(this.config) !== this.savedConfig
        throw error
      } finally {
        this.saving = false
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
      let draft = clone(found.step)
      mutator(draft, found)
      draft = shareUnchanged(found.step, draft)
      if (draft === found.step) return
      const normalize = dependencyStructureChanged(found.step, draft)
      this.record(label)
      for (const key of Object.keys(found.step)) {
        if (!(key in draft)) delete found.step[key]
      }
      Object.assign(found.step, draft)
      if (normalize) normalizeDependencies(this.selectedPreset.steps)
      this.changed()
    },
    setStepsEnabled(nodeIds, enabled) {
      const steps = nodeIds.map((id) => this.findStep(id).step).filter((step) => step && step.enabled !== enabled)
      if (!steps.length) return
      this.record(enabled ? '批量启用' : '批量停用')
      for (const step of steps) step.enabled = enabled
      this.changed()
    },
    deleteSteps(nodeIds) {
      const roots = selectedRoots(this.selectedPreset?.steps, new Set(nodeIds))
      if (!roots.length) return
      this.record('删除步骤')
      const byList = new Map()
      for (const { step, list } of roots) {
        if (!byList.has(list)) byList.set(list, new Set())
        byList.get(list).add(step)
      }
      for (const [list, removed] of byList) {
        for (let index = list.length - 1; index >= 0; index -= 1) {
          if (removed.has(list[index])) list.splice(index, 1)
        }
      }
      normalizeDependencies(this.selectedPreset.steps)
      this.changed()
    },
    duplicateStep(nodeId) {
      return this.duplicateSteps([nodeId])[0] || null
    },
    duplicateSteps(nodeIds) {
      // Traverse in execution order and stop below selected parents. Every
      // selected subtree is copied once, regardless of selection order.
      const roots = selectedRoots(this.selectedPreset?.steps, new Set(nodeIds))
      if (!roots.length) return []
      const idMap = new Map()
      const copies = roots.map(({ step }) => remapStep(step, idMap))
      copies.forEach((copy) => {
        applyRemappedDependencies(copy, idMap)
        copy.name = `${copy.name} 副本`
      })
      this.record('复制步骤')
      const byList = new Map()
      roots.forEach(({ step, list }, index) => {
        if (!byList.has(list)) byList.set(list, { insertAt: 0, copies: [] })
        const group = byList.get(list)
        group.insertAt = Math.max(group.insertAt, list.indexOf(step) + 1)
        group.copies.push(copies[index])
      })
      for (const [list, group] of byList) list.splice(group.insertAt, 0, ...group.copies)
      normalizeDependencies(this.selectedPreset.steps)
      this.changed()
      return roots.map(({ parent, branchIndex }, index) => parent
        ? branchNodeIdSafe(parent.id, branchIndex, copies[index].id)
        : copies[index].id)
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
      if (next.length !== this.selectedPreset.steps.length || new Set(next).size !== next.length
        || next.every((step, index) => step === this.selectedPreset.steps[index])) return
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
