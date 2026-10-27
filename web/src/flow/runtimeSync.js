// Build only when topology changes. Runtime notifications then touch changed
// steps and their adjacent edges, including every visual copy of a branch step.
export function createRuntimeIndex(nodes, edges) {
  const byStep = new Map()
  const byNode = new Map()
  const adjacent = new Map()
  const animated = new Set()
  for (const node of nodes) {
    const stepId = node.data?.step?.id
    if (!stepId) continue
    byNode.set(node.id, stepId)
    if (!byStep.has(stepId)) byStep.set(stepId, [])
    byStep.get(stepId).push(node)
  }
  for (const edge of edges) {
    if (edge.animated) animated.add(edge)
    for (const stepId of new Set([byNode.get(edge.source), byNode.get(edge.target)])) {
      if (!stepId) continue
      if (!adjacent.has(stepId)) adjacent.set(stepId, new Set())
      adjacent.get(stepId).add(edge)
    }
  }
  const stateOf = (states, nodeId) => {
    const runtime = states[byNode.get(nodeId)]
    return runtime?.state || runtime || 'idle'
  }
  function updateEdge(edge, states, running) {
    const active = running && (stateOf(states, edge.source) === 'running' || stateOf(states, edge.target) === 'running')
    if (edge.animated !== active) edge.animated = active
    if (active) animated.add(edge)
    else animated.delete(edge)
  }
  return {
    sync(states, running, ids = null, runningChanged = false) {
      const changedEdges = new Set(runningChanged ? animated : [])
      for (const stepId of ids ?? byStep.keys()) {
        const runtime = states[stepId]
        for (const node of byStep.get(stepId) || []) {
          const state = runtime?.state || runtime || 'idle'
          const error = runtime?.error || ''
          if (node.data.state !== state) node.data.state = state
          if (node.data.error !== error) node.data.error = error
          // Starting after a snapshot may enable previously inactive edges.
          if (runningChanged && state === 'running') for (const edge of adjacent.get(stepId) || []) changedEdges.add(edge)
        }
        for (const edge of adjacent.get(stepId) || []) changedEdges.add(edge)
      }
      for (const edge of changedEdges) updateEdge(edge, states, running)
    },
  }
}
