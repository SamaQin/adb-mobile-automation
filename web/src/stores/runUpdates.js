// Private, non-reactive indexes keep event work proportional to the changed frame.
// The bounded journal supports multiple canvases without a destructive dirty drain.
export const NODE_CHANGE_LIMIT = 512
export const LOG_LIMIT = 500
export const LOG_DEDUP_LIMIT = 1000
const indexes = new WeakMap()
let localLogId = 0

export function runIndex(store) {
  let index = indexes.get(store)
  if (!index) {
    index = { source: null, frames: new Map(), running: new Map(), journal: [], logIds: new Set() }
    indexes.set(store, index)
  }
  return index
}

export function indexNode(index, stepId, node, remove = false) {
  if (!node || typeof node !== 'object') return
  const frame = node.frame_id
  if (remove) {
    const members = index.frames.get(frame)
    members?.delete(stepId)
    if (!members?.size) index.frames.delete(frame)
    const active = index.running.get(frame)
    active?.delete(stepId)
    if (!active?.size) index.running.delete(frame)
  } else {
    if (!index.frames.has(frame)) index.frames.set(frame, new Set())
    index.frames.get(frame).add(stepId)
    if (node.state === 'running') {
      if (!index.running.has(frame)) index.running.set(frame, new Set())
      index.running.get(frame).add(stepId)
    }
  }
}

export function ensureNodeIndex(store) {
  const index = runIndex(store)
  if (index.source !== store.nodeStates) {
    index.source = store.nodeStates
    index.frames.clear()
    index.running.clear()
    for (const [id, node] of Object.entries(store.nodeStates)) indexNode(index, id, node)
  }
  return index
}

export function recordNodeChange(store, id = null) {
  const journal = runIndex(store).journal
  store.nodeRevision++
  // A replacement supersedes older incremental updates, including queued ones.
  if (id === null) journal.length = 0
  journal.push({ revision: store.nodeRevision, id })
  if (journal.length > NODE_CHANGE_LIMIT) journal.shift()
}

export function changesSince(store, revision) {
  if (revision === store.nodeRevision) return []
  const journal = runIndex(store).journal
  if (!journal.length || revision < journal[0].revision - 1) return null
  const ids = new Set()
  for (const change of journal) {
    if (change.revision <= revision) continue
    if (change.id === null) return null
    ids.add(change.id)
  }
  return [...ids]
}

export function eventLogId(event, kind = 'log') {
  return Number.isFinite(event.seq)
    ? `${event.server_id}:${event.run_id}:${event.seq}:${kind}`
    : `local:${++localLogId}:${kind}`
}
