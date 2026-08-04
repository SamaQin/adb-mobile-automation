export function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value))
}

export function displayToRaw(point, transform, imageSize) {
  const x = Math.round((point.x - transform.offsetX) / transform.scale)
  const y = Math.round((point.y - transform.offsetY) / transform.scale)
  return {
    x: clamp(x, 0, Math.max(0, imageSize.width - 1)),
    y: clamp(y, 0, Math.max(0, imageSize.height - 1)),
  }
}

export function rawRectFromDisplay(start, end, transform, imageSize) {
  const a = displayToRaw(start, transform, imageSize)
  const b = displayToRaw(end, transform, imageSize)
  const x = Math.min(a.x, b.x)
  const y = Math.min(a.y, b.y)
  return {
    x,
    y,
    width: Math.max(1, Math.abs(b.x - a.x)),
    height: Math.max(1, Math.abs(b.y - a.y)),
  }
}

export function fitTransform(container, image, zoom = 1) {
  const base = Math.min(container.width / image.width, container.height / image.height)
  const scale = base * zoom
  return {
    scale,
    offsetX: (container.width - image.width * scale) / 2,
    offsetY: (container.height - image.height * scale) / 2,
  }
}
