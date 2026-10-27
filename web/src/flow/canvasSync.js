import { branchNodeId } from './createFlow.js'

// Read only fields that affect node identity, handles, or connections. Ordinary
// editor fields remain reactive through node.data.step without rebuilding flow.
export function topologySignature(preset) {
  const describe = (step) => [
    step.id, step.kind, step.depends_on || [], step.params?.return_to || '',
    (step.params?.templates || []).map((template) => template.file),
    Object.entries(step.params?.branches || {}).map(([index, steps]) => [index, (steps || []).map(describe)]),
  ]
  return JSON.stringify([preset?.id, (preset?.steps || []).map(describe)])
}

export function stepBindings(preset) {
  const bindings = []
  for (const step of preset?.steps || []) {
    bindings.push({ id: step.id, step })
    for (const [index, steps] of Object.entries(step.params?.branches || {})) {
      for (const child of steps || []) bindings.push({ id: branchNodeId(step.id, index, child.id), step: child, siblings: steps })
    }
  }
  return bindings
}

export function syncNodeBindings(nodes, preset, definitions) {
  const bindings = new Map(stepBindings(preset).map((binding) => [binding.id, binding]))
  const defs = new Map(definitions.map((definition) => [definition.key, definition]))
  const names = new Map((preset?.steps || []).map((step) => [step.id, step.name]))
  for (const node of nodes) {
    if (node.id === 'start') node.data.label = preset?.name || '开始'
    const binding = bindings.get(node.id)
    if (!binding) continue
    node.data.step = binding.step
    node.data.def = defs.get(binding.step.kind)
    const target = binding.step.params?.return_to
    node.data.returnTargetName = target
      ? binding.siblings?.find((step) => step.id === target)?.name || names.get(target) || ''
      : ''
  }
}

export function handleSignature(node) {
  return JSON.stringify([node.type, Object.entries(node.data?.step?.params?.branches || {})
    .filter(([, steps]) => steps?.length).map(([index]) => index)])
}

export function reconcileById(current, incoming, { preservePosition = false } = {}) {
  const byId = new Map(current.map((item) => [item.id, item]))
  return incoming.map((item) => {
    const existing = byId.get(item.id)
    if (!existing || existing.type !== item.type) return item
    const position = existing.position
    const data = existing.data
    Object.assign(existing, item)
    if (data && item.data) existing.data = Object.assign(data, item.data)
    if (preservePosition) existing.position = position
    return existing
  })
}

export function draggedPositions({ node, nodes }) {
  return (nodes?.length ? nodes : node ? [node] : [])
    .filter((item) => item.type !== 'group')
    .map((item) => ({ id: item.id, position: { x: item.position.x, y: item.position.y } }))
}
