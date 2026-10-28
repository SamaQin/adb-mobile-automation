import { describe, expect, it } from 'vitest'
import {
  actionEnd,
  formatDuration,
  gestureToAction,
  mapPointerToDevice,
  recordingDuration,
} from './recordedActions.js'

describe('mapPointerToDevice', () => {
  it('maps the letterboxed canvas onto original device pixels', () => {
    const rect = { left: 100, top: 50, width: 400, height: 400 }
    // 100x200 media fits as 200x400 inside the square stage, centered at x=200..400.
    expect(mapPointerToDevice({ clientX: 300, clientY: 250 }, rect, 100, 200, { width: 1000, height: 2000 }))
      .toEqual({ x: 500, y: 1000 })
    expect(mapPointerToDevice({ clientX: 200, clientY: 50 }, rect, 100, 200, { width: 1000, height: 2000 }))
      .toEqual({ x: 0, y: 0 })
  })

  it('returns null when the stream or resolution is not ready', () => {
    const rect = { left: 0, top: 0, width: 400, height: 400 }
    expect(mapPointerToDevice({ clientX: 1, clientY: 1 }, rect, 0, 0, { width: 100, height: 200 })).toBeNull()
    expect(mapPointerToDevice({ clientX: 1, clientY: 1 }, rect, 100, 200, null)).toBeNull()
  })
})

describe('gestureToAction', () => {
  const resolution = { width: 1000, height: 2000 }

  it('records a tap when movement and hold are below thresholds', () => {
    expect(gestureToAction({
      start: { x: 100, y: 200 }, end: { x: 104, y: 203 },
      duration: 120, at: 0, resolution,
    })).toEqual({ type: 'tap', x: 100, y: 200, at: 0 })
  })

  it('records a long press as a same-point swipe', () => {
    expect(gestureToAction({
      start: { x: 100, y: 200 }, end: { x: 102, y: 200 },
      duration: 700, at: 300, resolution,
    })).toEqual({
      type: 'swipe', x1: 100, y1: 200, x2: 100, y2: 200,
      duration: 700, at: 300,
    })
  })

  it('records a drag as a swipe and clamps durations to the limit', () => {
    expect(gestureToAction({
      start: { x: 100, y: 200 }, end: { x: 400, y: 600 },
      duration: 9000, at: 1000, resolution,
    })).toEqual({
      type: 'swipe', x1: 100, y1: 200, x2: 400, y2: 600,
      duration: 5000, at: 1000,
    })
  })
})

describe('recording timing', () => {
  it('ends at the final swipe and ignores trailing time', () => {
    const actions = [
      { type: 'tap', x: 1, y: 2, at: 0 },
      { type: 'swipe', x1: 1, y1: 2, x2: 3, y2: 4, duration: 300, at: 1000 },
    ]
    expect(actionEnd(actions[0])).toBe(0)
    expect(actionEnd(actions[1])).toBe(1300)
    expect(recordingDuration(actions)).toBe(1300)
    expect(recordingDuration([])).toBe(0)
    expect(formatDuration(1300)).toBe('1.3 秒')
  })
})
