import { clone, normalizeDependencies } from './createFlow.js'

export function exportCanvas(preset, layout, nodes, edges) {
  return {
    format: 'adb-automation-canvas',
    version: 1,
    preset: clone(preset),
    layout: clone(layout),
    nodes: nodes.map(({ id, type, position, data }) => ({ id, type, position, order: data?.order })),
    edges: edges.map(({ id, source, target, sourceHandle, data }) => ({ id, source, target, sourceHandle, kind: data?.kind })),
  }
}

export function validateCanvasImport(value) {
  const errors = []
  if (!value || typeof value !== 'object') errors.push('JSON 根节点必须是对象')
  const preset = value?.preset
  if (!preset || typeof preset !== 'object') errors.push('缺少 preset')
  if (!Array.isArray(preset?.steps)) errors.push('preset.steps 必须是数组')

  const ids = new Set()
  for (const step of preset?.steps || []) {
    if (!step.id || ids.has(step.id)) errors.push(`步骤 ID 无效或重复: ${step.id || '空'}`)
    ids.add(step.id)
  }
  const seen = new Set()
  for (const step of preset?.steps || []) {
    for (const dependency of step.depends_on || []) {
      if (!ids.has(dependency)) errors.push(`${step.name || step.id} 引用了不存在的依赖 ${dependency}`)
      if (!seen.has(dependency)) errors.push(`${step.name || step.id} 包含后置依赖 ${dependency}`)
    }
    seen.add(step.id)
  }
  return { valid: errors.length === 0, errors }
}

export function importCanvas(value) {
  const result = validateCanvasImport(value)
  if (!result.valid) throw new Error(result.errors.join('\n'))
  const preset = clone(value.preset)
  normalizeDependencies(preset.steps)
  return { preset, layout: clone(value.layout || {}) }
}
