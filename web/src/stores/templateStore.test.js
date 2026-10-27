import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, expect, it, vi } from 'vitest'
import { useTemplateStore } from './templateStore.js'
import { fetchTemplates } from '../api/templates.js'

vi.mock('../api/templates.js', () => ({ fetchTemplates: vi.fn() }))
beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks() })

it('shares concurrent catalog requests and reuses a fresh immutable catalog', async () => {
  const store = useTemplateStore()
  let resolve
  fetchTemplates.mockImplementation(() => new Promise((done) => { resolve = done }))
  const first = store.load()
  const second = store.load()
  await Promise.resolve()
  resolve([{ name: 'a.png', revision: 'first' }])
  await Promise.all([first, second])
  await store.load()
  expect(fetchTemplates).toHaveBeenCalledTimes(1)
  expect(store.byName.get('a.png').revision).toBe('first')
  expect(store.loading).toBe(false)
})

it('does not publish stale results when the catalog is invalidated during a request', async () => {
  const store = useTemplateStore()
  let resolve
  fetchTemplates.mockImplementationOnce(() => new Promise((done) => { resolve = done }))
  const old = store.load()
  await Promise.resolve()
  store.invalidate()
  fetchTemplates.mockResolvedValueOnce([{ name: 'new.png' }])
  const fresh = store.load()
  await fresh
  resolve([{ name: 'old.png' }])
  await old
  expect(store.items.map((item) => item.name)).toEqual(['new.png'])
  expect(fetchTemplates).toHaveBeenCalledTimes(2)
})
