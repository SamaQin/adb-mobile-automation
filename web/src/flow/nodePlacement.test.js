import { describe, expect, it } from 'vitest'
import { visibleNodePosition } from './nodePlacement.js'

describe('visible node placement', () => {
  it.each([0.3, 1, 2])('respects pan and zoom at scale %s', (zoom) => {
    const pan = { x: -3000, y: -9000 }
    const rect = { left: 220, top: 140, width: 800, height: 600 }
    const screenToFlowCoordinate = ({ x, y }) => ({ x: (x - rect.left - pan.x) / zoom, y: (y - rect.top - pan.y) / zoom })
    const position = visibleNodePosition({ rect, zoom, screenToFlowCoordinate })
    const screen = { x: position.x * zoom + pan.x, y: position.y * zoom + pan.y }
    expect(screen.x).toBeGreaterThanOrEqual(12)
    expect(screen.y).toBeGreaterThanOrEqual(64)
    expect(screen.x + 242 * zoom).toBeLessThanOrEqual(788)
    expect(screen.y + 140 * zoom).toBeLessThanOrEqual(588)
  })

  it('prefers a visible space away from existing nodes without changing them', () => {
    const options = { rect: { left: 0, top: 0, width: 800, height: 600 }, screenToFlowCoordinate: (point) => point }
    const center = visibleNodePosition(options)
    const nodes = [{ id: 'a', type: 'step', position: center }]
    const added = visibleNodePosition({ ...options, nodes })
    expect(added).not.toEqual(center)
    expect(nodes[0].position).toEqual(center)
  })
})
