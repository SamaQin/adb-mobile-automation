export function cloneJson(value) {
  return value == null ? value : JSON.parse(JSON.stringify(value))
}
