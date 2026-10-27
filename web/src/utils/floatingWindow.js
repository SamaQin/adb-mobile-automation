export const MONITOR_GEOMETRY_KEY = 'ui:device-monitor:geometry'
export const MONITOR_MIN_WIDTH = 248
export const MONITOR_MIN_HEIGHT = 300

const DEFAULT_WIDTH = 282
const DEFAULT_HEIGHT = 560
const DEFAULT_MARGIN = 18

function finiteNumber(value, fallback) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), maximum)
}

function viewportSize(viewport) {
  return {
    width: Math.max(1, Math.round(finiteNumber(viewport?.width, 1280))),
    height: Math.max(1, Math.round(finiteNumber(viewport?.height, 800))),
  }
}

export function defaultMonitorGeometry(viewport = { width: 1280, height: 800 }) {
  const size = viewportSize(viewport)
  const width = Math.min(
    Math.max(MONITOR_MIN_WIDTH, Math.round(size.width * 0.22)),
    Math.min(320, size.width),
  )
  const height = Math.min(
    DEFAULT_HEIGHT,
    Math.max(MONITOR_MIN_HEIGHT, size.height - DEFAULT_MARGIN * 2),
    size.height,
  )
  return {
    x: Math.max(0, size.width - width - DEFAULT_MARGIN),
    y: Math.max(0, size.height - height - DEFAULT_MARGIN),
    width,
    height,
  }
}

export function normalizeMonitorGeometry(candidate, viewport = { width: 1280, height: 800 }) {
  const size = viewportSize(viewport)
  const fallback = defaultMonitorGeometry(size)
  const minimumWidth = Math.min(MONITOR_MIN_WIDTH, size.width)
  const minimumHeight = Math.min(MONITOR_MIN_HEIGHT, size.height)
  const width = Math.round(clamp(finiteNumber(candidate?.width, fallback.width), minimumWidth, size.width))
  const height = Math.round(clamp(finiteNumber(candidate?.height, fallback.height), minimumHeight, size.height))
  return {
    x: Math.round(clamp(finiteNumber(candidate?.x, fallback.x), 0, Math.max(0, size.width - width))),
    y: Math.round(clamp(finiteNumber(candidate?.y, fallback.y), 0, Math.max(0, size.height - height))),
    width,
    height,
  }
}

export function moveMonitorGeometry(origin, deltaX, deltaY, viewport) {
  return normalizeMonitorGeometry({
    ...origin,
    x: finiteNumber(origin?.x, 0) + finiteNumber(deltaX, 0),
    y: finiteNumber(origin?.y, 0) + finiteNumber(deltaY, 0),
  }, viewport)
}

export function resizeMonitorGeometry(origin, deltaX, deltaY, viewport = { width: 1280, height: 800 }) {
  const size = viewportSize(viewport)
  const base = normalizeMonitorGeometry(origin, size)
  const maximumWidth = Math.max(MONITOR_MIN_WIDTH, size.width - base.x)
  const maximumHeight = Math.max(MONITOR_MIN_HEIGHT, size.height - base.y)
  return {
    x: base.x,
    y: base.y,
    width: Math.round(clamp(base.width + finiteNumber(deltaX, 0), Math.min(MONITOR_MIN_WIDTH, maximumWidth), maximumWidth)),
    height: Math.round(clamp(base.height + finiteNumber(deltaY, 0), Math.min(MONITOR_MIN_HEIGHT, maximumHeight), maximumHeight)),
  }
}

export function readMonitorGeometry(storage, viewport = { width: 1280, height: 800 }) {
  const fallback = defaultMonitorGeometry(viewport)
  try {
    const stored = JSON.parse(storage?.getItem?.(MONITOR_GEOMETRY_KEY) || 'null')
    return stored && typeof stored === 'object' ? normalizeMonitorGeometry(stored, viewport) : fallback
  } catch {
    return fallback
  }
}

export function saveMonitorGeometry(storage, geometry) {
  try {
    storage?.setItem?.(MONITOR_GEOMETRY_KEY, JSON.stringify(geometry))
  } catch {
    // Local storage can be unavailable in private browsing; geometry is best-effort.
  }
}
