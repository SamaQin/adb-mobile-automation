import { vi } from 'vitest'

if (!globalThis.structuredClone) globalThis.structuredClone = (value) => JSON.parse(JSON.stringify(value))
if (!globalThis.crypto?.randomUUID) {
  Object.defineProperty(globalThis, 'crypto', { value: { randomUUID: vi.fn(() => '00000000-0000-4000-8000-000000000001') } })
}

// Node 25 may expose a partial native storage object in jsdom tests.
for (const name of ['localStorage', 'sessionStorage']) {
  if (typeof globalThis[name]?.clear === 'function') continue
  const data = new Map()
  const storage = {
    getItem: (key) => data.get(String(key)) ?? null,
    setItem: (key, value) => { data.set(String(key), String(value)) },
    removeItem: (key) => { data.delete(String(key)) },
    clear: () => data.clear(),
    key: (index) => [...data.keys()][index] ?? null,
    get length() { return data.size },
  }
  Object.defineProperty(globalThis, name, { configurable: true, value: storage })
  Object.defineProperty(window, name, { configurable: true, value: storage })
}

globalThis.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
}
