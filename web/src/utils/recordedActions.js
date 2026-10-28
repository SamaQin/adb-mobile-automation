export const MAX_ACTIONS = 1000
export const MAX_GESTURE_MS = 5000
export const TAP_DISTANCE = 8
export const LONG_PRESS_MS = 500

function clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value))
}

export function actionEnd(action) {
  const at = Number(action?.at) || 0
  return action?.type === 'swipe' ? at + (Number(action.duration) || 0) : at
}

export function recordingDuration(actions) {
  return actions?.length ? actionEnd(actions[actions.length - 1]) : 0
}

export function formatDuration(milliseconds) {
  return `${(Math.max(0, Number(milliseconds) || 0) / 1000).toFixed(1)} 秒`
}

export function mapPointerToDevice(point, rect, canvasWidth, canvasHeight, resolution) {
  if (!rect || !canvasWidth || !canvasHeight || !resolution?.width || !resolution?.height) {
    return null
  }
  const scale = Math.min(rect.width / canvasWidth, rect.height / canvasHeight)
  if (!scale || !Number.isFinite(scale)) return null
  const renderWidth = canvasWidth * scale
  const renderHeight = canvasHeight * scale
  const left = rect.left + (rect.width - renderWidth) / 2
  const top = rect.top + (rect.height - renderHeight) / 2
  const x = ((point.clientX - left) / renderWidth) * resolution.width
  const y = ((point.clientY - top) / renderHeight) * resolution.height
  return {
    x: clamp(Math.round(x), 0, Math.max(0, resolution.width - 1)),
    y: clamp(Math.round(y), 0, Math.max(0, resolution.height - 1)),
  }
}

export function gestureToAction({ start, end, duration, at, resolution }) {
  const distance = Math.hypot(end.x - start.x, end.y - start.y)
  const hold = clamp(Math.round(duration), 1, MAX_GESTURE_MS)
  const when = Math.max(0, Math.round(at))
  if (distance < TAP_DISTANCE && hold < LONG_PRESS_MS) {
    return { type: 'tap', x: start.x, y: start.y, at: when }
  }
  if (distance < TAP_DISTANCE) {
    return {
      type: 'swipe', x1: start.x, y1: start.y, x2: start.x, y2: start.y,
      duration: hold, at: when,
    }
  }
  return {
    type: 'swipe', x1: start.x, y1: start.y, x2: end.x, y2: end.y,
    duration: hold, at: when,
  }
}
