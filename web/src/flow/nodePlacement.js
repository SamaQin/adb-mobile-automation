const NODE_WIDTH = 242
const NODE_HEIGHT = 140

// Layout coordinates remain independent of the preset's execution order.
export function visibleNodePosition({ rect, zoom = 1, screenToFlowCoordinate, nodes = [], point = null }) {
  const scale = Math.max(0.1, zoom)
  const width = rect.width || 640
  const height = rect.height || 480
  const left = rect.left + 12
  const top = rect.top + 64
  const right = Math.max(left, rect.left + width - NODE_WIDTH * scale - 12)
  const bottom = Math.max(top, rect.top + height - NODE_HEIGHT * scale - 12)
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value))
  const at = (x, y) => screenToFlowCoordinate({ x: clamp(x, left, right), y: clamp(y, top, bottom) })
  if (point) return at(point.x, point.y)

  const center = { x: rect.left + width / 2 - NODE_WIDTH * scale / 2, y: rect.top + height * 0.45 - NODE_HEIGHT * scale / 2 }
  const candidates = [at(center.x, center.y)]
  for (const y of [top, (top + bottom) / 2, bottom]) {
    for (const x of [left, (left + right) / 2, right]) candidates.push(at(x, y))
  }
  const overlaps = (position) => nodes.filter((node) => node.type !== 'group' &&
    position.x < node.position.x + (node.type === 'start' ? 88 : NODE_WIDTH) + 16 &&
    position.x + NODE_WIDTH + 16 > node.position.x &&
    position.y < node.position.y + (node.type === 'start' ? 88 : NODE_HEIGHT) + 16 &&
    position.y + NODE_HEIGHT + 16 > node.position.y).length
  return candidates.reduce((best, candidate) => overlaps(candidate) < overlaps(best) ? candidate : best)
}
