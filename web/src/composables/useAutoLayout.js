import { createDefaultLayout } from '../flow/createFlow.js'

export function autoLayoutForPreset(preset) {
  return createDefaultLayout(preset)
}

export function orderByLayout(steps, layout) {
  return [...steps].sort((a, b) => {
    const pa = layout[a.id] || { x: 0, y: 0 }
    const pb = layout[b.id] || { x: 0, y: 0 }
    return pa.y - pb.y || pa.x - pb.x
  })
}
