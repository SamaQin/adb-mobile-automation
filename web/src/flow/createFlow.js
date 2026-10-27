const MAIN_X = 80
const MAIN_NODE_WIDTH = 242
const START_NODE_WIDTH = 88
const START_X = MAIN_X + (MAIN_NODE_WIDTH - START_NODE_WIDTH) / 2
const START_Y = 8
const FIRST_ROW_Y = 230
const ROW_GAP = 170
const SPECIAL_X_GAP = 320
const SPECIAL_ROW_GAP = 132
const BRANCH_X_GAP = 330
const BRANCH_Y_GAP = 146

export function clone(value) {
  return cloneJson(value)
}

export function branchNodeId(parentId, index, stepId) {
  return `branch:${parentId}:${index}:${stepId}`
}

export function parseBranchNodeId(nodeId) {
  if (!nodeId?.startsWith('branch:')) return null
  const [, parentStepId, index, ...stepId] = nodeId.split(':')
  if (!parentStepId || index === undefined || !stepId.length) return null
  return { parentStepId, index: String(index), stepId: stepId.join(':') }
}

function hasDependencies(step) {
  return Boolean(step?.depends_on?.length)
}

function listPositions(steps, nodeId, baseX, baseY, rowGap) {
  const positions = {}
  const specialSlots = new Map()
  let mainIndex = 0

  for (const step of steps) {
    const id = nodeId(step.id)
    if (!hasDependencies(step)) {
      positions[id] = { x: baseX, y: baseY + mainIndex * rowGap }
      mainIndex += 1
      continue
    }

    const dependency = step.depends_on.find((dependencyId) => positions[nodeId(dependencyId)])
    const sourceId = dependency ? nodeId(dependency) : null
    const source = sourceId ? positions[sourceId] : null
    const slot = specialSlots.get(sourceId) || 0
    positions[id] = source
      ? { x: source.x + SPECIAL_X_GAP, y: source.y + slot * SPECIAL_ROW_GAP }
      : { x: baseX + SPECIAL_X_GAP, y: baseY + mainIndex * rowGap }
    if (sourceId) specialSlots.set(sourceId, slot + 1)
  }
  return positions
}

export function createDefaultLayout(preset) {
  const steps = preset?.steps || []
  const layout = {
    start: { x: START_X, y: START_Y },
    ...listPositions(steps, (id) => id, MAIN_X, FIRST_ROW_Y, ROW_GAP),
  }
  for (const step of steps) {
    const parent = layout[step.id] || { x: MAIN_X, y: FIRST_ROW_Y }
    for (const [branchIndex, branchSteps] of Object.entries(step.params?.branches || {})) {
      Object.assign(layout, listPositions(
        branchSteps || [],
        (id) => branchNodeId(step.id, branchIndex, id),
        parent.x + (Number(branchIndex) + 1) * BRANCH_X_GAP,
        parent.y + ROW_GAP,
        BRANCH_Y_GAP,
      ))
    }
  }
  return layout
}

function edge(source, target, kind, extra = {}) {
  const suffix = extra.sourceHandle ? `:${extra.sourceHandle}` : ''
  return {
    id: `${kind}:${source}:${target}${suffix}`,
    source,
    target,
    type: 'smoothstep',
    class: `edge-${kind}`,
    data: { kind, ...extra.data },
    sourceHandle: extra.sourceHandle,
    targetHandle: extra.targetHandle,
    animated: Boolean(extra.animated),
    selectable: ['dependency', 'return'].includes(kind),
    deletable: ['dependency', 'return'].includes(kind),
    style: kind === 'dependency'
      ? { stroke: '#38bdf8', strokeWidth: 1.8 }
      : kind === 'branch'
        ? { stroke: '#fbbf24', strokeWidth: 1.5 }
        : kind === 'return'
          ? { stroke: '#f472b6', strokeWidth: 1.6, strokeDasharray: '6 4' }
          : { stroke: '#718096', strokeWidth: 1.2, strokeDasharray: '5 5' },
  }
}

function dependencyCounts(steps) {
  const counts = new Map()
  for (const step of steps) {
    for (const dependencyId of step.depends_on || []) {
      counts.set(dependencyId, (counts.get(dependencyId) || 0) + 1)
    }
  }
  return counts
}

function appendDefaultChain(edges, steps, nodeId, source, sourceHandle, kind) {
  const defaultSteps = steps.filter((step) => !hasDependencies(step))
  defaultSteps.forEach((step, index) => {
    const previous = index === 0 ? source : nodeId(defaultSteps[index - 1].id)
    edges.push(edge(previous, nodeId(step.id), kind, {
      sourceHandle: index === 0 ? sourceHandle : 'order-source',
      targetHandle: 'order-target',
    }))
  })
}

export function createFlow(preset, definitions = [], layout = {}, runtimeStates = {}) {
  const defaultLayout = createDefaultLayout(preset)
  const nodes = [{
    id: 'start',
    type: 'start',
    position: clone(layout.start || defaultLayout.start),
    selectable: false,
    data: { order: 0, label: preset?.name || '开始', state: 'idle' },
  }]
  const edges = []
  const definitionMap = new Map(definitions.map((item) => [item.key, item]))
  const steps = preset?.steps || []
  const mainDependencyCounts = dependencyCounts(steps)
  const mainNames = new Map(steps.map((step) => [step.id, step.name]))

  steps.forEach((step, index) => {
    const order = index + 1
    nodes.push({
      id: step.id,
      type: 'step',
      position: clone(layout[step.id] || defaultLayout[step.id]),
      data: {
        step,
        order,
        def: definitionMap.get(step.kind),
        state: runtimeStates[step.id]?.state || runtimeStates[step.id] || 'idle',
        error: runtimeStates[step.id]?.error || '',
        isBranch: false,
        isSpecial: hasDependencies(step),
        outgoingDependencyCount: mainDependencyCounts.get(step.id) || 0,
        returnTargetName: step.params?.return_to ? (mainNames.get(step.params.return_to) || '') : '',
      },
    })

    const branches = step.params?.branches || {}
    Object.entries(branches).forEach(([branchIndex, branchSteps]) => {
      const template = step.params?.templates?.[Number(branchIndex)]
      const branchId = (id) => branchNodeId(step.id, branchIndex, id)
      const branchDependencyCounts = dependencyCounts(branchSteps || [])
      const branchNames = new Map((branchSteps || []).map((item) => [item.id, item.name]))
      ;(branchSteps || []).forEach((branchStep, branchStepIndex) => {
        const id = branchId(branchStep.id)
        nodes.push({
          id,
          type: 'branch',
          position: clone(layout[id] || defaultLayout[id]),
          data: {
            step: branchStep,
            order: branchStepIndex + 1,
            def: definitionMap.get(branchStep.kind),
            state: runtimeStates[branchStep.id]?.state || runtimeStates[branchStep.id] || 'idle',
            error: runtimeStates[branchStep.id]?.error || '',
            isBranch: true,
            isSpecial: hasDependencies(branchStep),
            outgoingDependencyCount: branchDependencyCounts.get(branchStep.id) || 0,
            branch: {
              parentStepId: step.id,
              index: String(branchIndex),
              label: template?.file || `分支 ${Number(branchIndex) + 1}`,
            },
            returnTargetName: (() => {
              const target = branchStep.params?.return_to
              if (!target) return ''
              return branchNames.get(target) || mainNames.get(target) || ''
            })(),
          },
        })
      })
      appendDefaultChain(edges, branchSteps || [], branchId, step.id, `branch-${branchIndex}`, 'branch')
      for (const branchStep of branchSteps || []) {
        for (const dependencyId of branchStep.depends_on || []) {
          edges.push(edge(branchId(dependencyId), branchId(branchStep.id), 'dependency', {
            sourceHandle: 'dependency-source',
            targetHandle: 'order-target',
            data: { branchDependency: true },
          }))
        }
        if (branchStep.params?.return_to) {
          const inBranch = (branchSteps || []).some((item) => item.id === branchStep.params.return_to)
          const inMain = steps.some((item) => item.id === branchStep.params.return_to)
          if (inBranch) {
            edges.push(edge(branchId(branchStep.id), branchId(branchStep.params.return_to), 'return', {
              sourceHandle: 'order-source',
              targetHandle: 'order-target',
            }))
          } else if (inMain) {
            edges.push(edge(branchId(branchStep.id), branchStep.params.return_to, 'return', {
              sourceHandle: 'order-source',
              targetHandle: 'order-target',
            }))
          }
        }
      }
    })
  })

  appendDefaultChain(edges, steps, (id) => id, 'start', 'order-source', 'order')

  steps.forEach((step) => {
    for (const dependencyId of step.depends_on || []) {
      edges.push(edge(dependencyId, step.id, 'dependency', {
        sourceHandle: 'dependency-source',
        targetHandle: 'order-target',
        data: { special: true },
      }))
    }
    if (step.params?.return_to && steps.some((item) => item.id === step.params.return_to)) {
      edges.push(edge(step.id, step.params.return_to, 'return', {
        sourceHandle: 'order-source',
        targetHandle: 'order-target',
      }))
    }
  })

  return { nodes, edges }
}

export function normalizeDependencies(steps) {
  const mainIds = new Set()
  const collect = (list, isMain) => {
    for (const step of list || []) {
      if (isMain) mainIds.add(step.id)
      for (const branchSteps of Object.values(step.params?.branches || {})) collect(branchSteps, false)
    }
  }
  collect(steps, true)
  const normalize = (list, isBranch) => {
    const seen = new Set()
    for (const step of list) {
      step.depends_on = [...new Set(step.depends_on || [])].filter((id) => seen.has(id))
      const target = step.params?.return_to
      if (target != null) {
        const valid = isBranch ? (seen.has(target) || mainIds.has(target)) : seen.has(target)
        if (!valid) delete step.params.return_to
      }
      seen.add(step.id)
      for (const branchSteps of Object.values(step.params?.branches || {})) normalize(branchSteps || [], true)
    }
  }
  normalize(steps, false)
  return steps
}

export function flowToPreset(preset, nodes, edges) {
  const result = clone(preset)
  const mainNodes = nodes
    .filter((node) => node.data?.step && !node.data?.isBranch)
    .sort((a, b) => a.data.order - b.data.order)
  const stepById = new Map((result.steps || []).map((step) => [step.id, step]))
  result.steps = mainNodes.map((node) => clone(stepById.get(node.id) || node.data.step))

  for (const step of result.steps) {
    step.depends_on = edges
      .filter((item) => item.target === step.id && item.data?.kind === 'dependency' && item.source !== 'start')
      .map((item) => item.source)
    const returnEdge = edges.find((item) => item.source === step.id && item.data?.kind === 'return')
    if (returnEdge) step.params.return_to = returnEdge.target
    else delete step.params.return_to
  }

  normalizeDependencies(result.steps)
  return result
}
import { cloneJson } from '../utils/clone.js'
