import { describe, expect, it } from 'vitest'
import { displayToRaw, fitTransform, rawRectFromDisplay } from './useScreenshotEditor.js'

describe('screenshot coordinate conversion', () => {
  it('maps display coordinates to original pixels and clamps bounds', () => {
    const transform = { scale: 0.5, offsetX: 10, offsetY: 20 }
    const image = { width: 1080, height: 2400 }
    expect(displayToRaw({ x: 60, y: 120 }, transform, image)).toEqual({ x: 100, y: 200 })
    expect(displayToRaw({ x: -100, y: 9999 }, transform, image)).toEqual({ x: 0, y: 2399 })
  })

  it('normalizes reverse rectangle drags with at least one pixel', () => {
    const transform = { scale: 2, offsetX: 0, offsetY: 0 }
    const image = { width: 100, height: 100 }
    expect(rawRectFromDisplay({ x: 80, y: 60 }, { x: 20, y: 10 }, transform, image)).toEqual({ x: 10, y: 5, width: 30, height: 25 })
    expect(rawRectFromDisplay({ x: 20, y: 20 }, { x: 20, y: 20 }, transform, image).width).toBe(1)
  })

  it('fits an image into the available canvas without distortion', () => {
    expect(fitTransform({ width: 800, height: 600 }, { width: 1600, height: 900 })).toEqual({ scale: 0.5, offsetX: 0, offsetY: 75 })
  })
})
