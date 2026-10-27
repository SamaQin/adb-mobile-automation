import { describe, expect, it } from 'vitest'
import {
  MONITOR_GEOMETRY_KEY,
  MONITOR_MIN_HEIGHT,
  MONITOR_MIN_WIDTH,
  defaultMonitorGeometry,
  moveMonitorGeometry,
  normalizeMonitorGeometry,
  readMonitorGeometry,
  resizeMonitorGeometry,
  saveMonitorGeometry,
} from './floatingWindow.js'

const viewport = { width: 1280, height: 800 }

describe('floating monitor geometry', () => {
  it('opens with a portrait-sized window inside the viewport', () => {
    const geometry = defaultMonitorGeometry(viewport)

    expect(geometry.width).toBeGreaterThanOrEqual(MONITOR_MIN_WIDTH)
    expect(geometry.height).toBeGreaterThanOrEqual(MONITOR_MIN_HEIGHT)
    expect(geometry.x).toBeGreaterThanOrEqual(0)
    expect(geometry.y).toBeGreaterThanOrEqual(0)
    expect(geometry.x + geometry.width).toBeLessThanOrEqual(viewport.width)
    expect(geometry.y + geometry.height).toBeLessThanOrEqual(viewport.height)
  })

  it('keeps stored and malformed geometry fully visible', () => {
    expect(normalizeMonitorGeometry({ x: -90, y: 900, width: 120, height: 9999 }, viewport)).toEqual({
      x: 0,
      y: 0,
      width: MONITOR_MIN_WIDTH,
      height: 800,
    })
    expect(normalizeMonitorGeometry(null, viewport)).toEqual(defaultMonitorGeometry(viewport))
  })

  it('moves and resizes without leaving the viewport', () => {
    const origin = { x: 700, y: 200, width: 300, height: 400 }

    expect(moveMonitorGeometry(origin, 1000, -1000, viewport)).toEqual({
      x: 980,
      y: 0,
      width: 300,
      height: 400,
    })
    expect(resizeMonitorGeometry(origin, -500, -500, viewport)).toEqual({
      x: 700,
      y: 200,
      width: MONITOR_MIN_WIDTH,
      height: MONITOR_MIN_HEIGHT,
    })
    expect(resizeMonitorGeometry(origin, 1000, 1000, viewport)).toEqual({
      x: 700,
      y: 200,
      width: 580,
      height: 600,
    })
  })

  it('persists and restores the last geometry', () => {
    const values = new Map()
    const storage = {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
    }
    const geometry = { x: 120, y: 80, width: 310, height: 500 }

    saveMonitorGeometry(storage, geometry)

    expect(JSON.parse(values.get(MONITOR_GEOMETRY_KEY))).toEqual(geometry)
    expect(readMonitorGeometry(storage, viewport)).toEqual(geometry)
  })

  it('falls back safely when local storage is corrupt', () => {
    const storage = {
      getItem: () => '{not-json',
      setItem: () => { throw new Error('quota exceeded') },
    }

    expect(readMonitorGeometry(storage, viewport)).toEqual(defaultMonitorGeometry(viewport))
    expect(() => saveMonitorGeometry(storage, defaultMonitorGeometry(viewport))).not.toThrow()
  })
})
