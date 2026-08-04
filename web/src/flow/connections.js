function hasPath(edges, from, to, visited = new Set()) {
  if (from === to) return true
  if (visited.has(from)) return false
  visited.add(from)
  return edges
    .filter((edge) => edge.data?.kind === 'dependency' && edge.source === from)
    .some((edge) => hasPath(edges, edge.target, to, visited))
}

export function connectionKind(connection, nodes = []) {
  if (connection.source === 'start') return 'order'
  if (connection.sourceHandle?.startsWith('branch-')) return 'branch'
  if (connection.sourceHandle === 'order-source') {
    const source = nodes.find((node) => node.id === connection.source)
    const target = nodes.find((node) => node.id === connection.target)
    if (source?.data?.branch) {
      const sameLane = target?.data?.branch
        && target.data.branch.parentStepId === source.data.branch.parentStepId
        && target.data.branch.index === source.data.branch.index
      if (sameLane && Number(source.data?.order) < Number(target.data?.order)) return 'order'
      return 'return'
    }
    if (source && target && Number(source.data?.order) > Number(target.data?.order)) return 'return'
    return 'order'
  }
  return 'dependency'
}

export function validateConnection(connection, nodes, edges) {
  const source = nodes.find((node) => node.id === connection.source)
  const target = nodes.find((node) => node.id === connection.target)
  if (!source || !target) return { valid: false, reason: '连接端点不存在' }
  if (target.id === 'start') return { valid: false, reason: '开始节点不能接收入边' }
  if (source.id === target.id) return { valid: false, reason: '步骤不能依赖自身' }
  if (connection.targetHandle && connection.targetHandle !== 'order-target') return { valid: false, reason: '连接必须进入节点上方点位' }

  const kind = connectionKind(connection, nodes)
  const sourceBranch = source.data?.branch
  const targetBranch = target.data?.branch

  if (kind === 'branch') {
    const branchIndex = connection.sourceHandle.slice('branch-'.length)
    if (!targetBranch || targetBranch.parentStepId !== source.id || targetBranch.index !== branchIndex) {
      return { valid: false, reason: '模板分支只能连接自身分支内的步骤' }
    }
    if (target.data?.step?.depends_on?.length) return { valid: false, reason: '分支入口不能连接带前置依赖的步骤' }
    return { valid: true }
  }

  if (kind === 'order') {
    if (source.id === 'start') {
      if (targetBranch || target.data?.step?.depends_on?.length) return { valid: false, reason: '开始节点只能连接主流程默认步骤' }
      return { valid: true }
    }
    if (Boolean(sourceBranch) !== Boolean(targetBranch)) return { valid: false, reason: '主流程与分支流程不能建立顺序连接' }
    if (sourceBranch && (sourceBranch.parentStepId !== targetBranch.parentStepId || sourceBranch.index !== targetBranch.index)) {
      return { valid: false, reason: '不同分支之间不能建立顺序连接' }
    }
    if (source.data?.step?.depends_on?.length || target.data?.step?.depends_on?.length) {
      return { valid: false, reason: '默认顺序连接不能包含特殊依赖步骤' }
    }
    return { valid: true }
  }

  if (kind === 'return') {
    if (sourceBranch) {
      if (targetBranch) {
        if (targetBranch.parentStepId !== sourceBranch.parentStepId || targetBranch.index !== sourceBranch.index) {
          return { valid: false, reason: '不同分支之间不能建立返回连接' }
        }
        if (Number(target.data?.order) >= Number(source.data?.order)) return { valid: false, reason: '返回连接只能指向更早的步骤' }
      } else {
        const parent = nodes.find((node) => node.id === sourceBranch.parentStepId)
        const parentOrder = Number(parent?.data?.order ?? Infinity)
        if (Number(target.data?.order) > parentOrder) return { valid: false, reason: '返回连接只能指向更早的步骤' }
      }
    } else {
      if (targetBranch) return { valid: false, reason: '主流程步骤不能返回到分支步骤' }
      if (Number(source.data?.order) <= Number(target.data?.order)) return { valid: false, reason: '返回连接只能指向更早的步骤' }
    }
    if (edges.some((edge) => (
      (!connection.id || edge.id !== connection.id)
      && edge.source === source.id
      && edge.target === target.id
      && (edge.data?.kind === 'return' || edge.data?.kind === 'order')
    ))) {
      return { valid: false, reason: '该返回连接已存在', duplicate: true }
    }
    return { valid: true }
  }

  if (Boolean(sourceBranch) !== Boolean(targetBranch)) {
    return { valid: false, reason: '主流程与分支流程不能建立依赖' }
  }
  if (sourceBranch && (sourceBranch.parentStepId !== targetBranch.parentStepId || sourceBranch.index !== targetBranch.index)) {
    return { valid: false, reason: '不同分支之间不能建立依赖' }
  }
  if (Number(source.data?.order) >= Number(target.data?.order)) {
    return { valid: false, reason: '依赖只能从更早步骤指向更晚步骤' }
  }
  if (edges.some((edge) => (
    (!connection.id || edge.id !== connection.id)
    && edge.source === source.id
    && edge.target === target.id
    && edge.data?.kind === 'dependency'
  ))) {
    return { valid: false, reason: '该依赖已存在', duplicate: true }
  }
  if (hasPath(edges, target.id, source.id)) return { valid: false, reason: '该连接会形成循环依赖' }
  return { valid: true }
}

export function dependencyEdge(source, target) {
  return {
    id: `dependency:${source}:${target}`,
    source,
    target,
    sourceHandle: 'dependency-source',
    targetHandle: 'order-target',
    type: 'smoothstep',
    class: 'edge-dependency',
    data: { kind: 'dependency' },
    style: { stroke: '#38bdf8', strokeWidth: 1.8 },
  }
}
