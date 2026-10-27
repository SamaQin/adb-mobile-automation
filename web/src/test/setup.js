import { vi } from 'vitest'

if (!globalThis.structuredClone) globalThis.structuredClone = (value) => JSON.parse(JSON.stringify(value))
if (!globalThis.crypto?.randomUUID) {
  Object.defineProperty(globalThis, 'crypto', { value: { randomUUID: vi.fn(() => '00000000-0000-4000-8000-000000000001') } })
}

globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
}
