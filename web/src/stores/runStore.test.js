import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useRunStore } from './runStore.js'
import { fetchRunStatus, startRun } from '../api/run.js'
import { LOG_DEDUP_LIMIT, NODE_CHANGE_LIMIT, runIndex } from './runUpdates.js'

vi.mock('../api/run.js', () => ({ fetchRunStatus: vi.fn(), startRun: vi.fn(), stopRun: vi.fn() }))
beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks() })
const event = (type, seq, data, run_id = 'run') => ({ type, seq, run_id, data })

describe('authoritative run recovery', () => {
  it('restores nested snapshots and ignores stale backlog or HTTP responses', async () => {
    const store = useRunStore()
    const nodes = { parent: { state: 'running', frame_id: 'root' }, child: { state: 'done', frame_id: 'child' } }
    store.handleEvent(event('status', 20, { state: 'running', node_states: nodes, cycle: 3, root_cycle: 1 }))
    store.handleEvent(event('step', 19, { step_id: 'child', state: 'running' }))
    fetchRunStatus.mockResolvedValue({ seq: 18, run_id: 'run', state: 'idle', node_states: {} })
    await store.refreshStatus()
    expect(store.state).toBe('running')
    expect(store.nodeStates).toEqual(nodes)
    store.handleEvent(event('status', 21, { state: 'running', cycle: 1, root_cycle: 1, preset_id: 'root' }))
    expect(store.nodeStates).toEqual(nodes)
    store.handleEvent(event('status', 22, { state: 'running', root_cycle: 2 }))
    expect(store.nodeStates).toEqual({})
  })

  it('keeps parent running while nested steps run and complete', () => {
    const store = useRunStore()
    store.handleEvent(event('step', 1, { step_id: 'parent', frame_id: 'root', state: 'running' }))
    store.handleEvent(event('step', 2, { step_id: 'child', frame_id: 'child', state: 'running' }))
    expect(store.nodeStates.parent.state).toBe('running')
    store.handleEvent(event('step', 3, { step_id: 'child', frame_id: 'child', state: 'done' }))
    store.handleEvent(event('step', 4, { step_id: 'parent', frame_id: 'root', state: 'done' }))
    expect(store.nodeStates.parent.state).toBe('done')
    expect(store.nodeStates.child.state).toBe('done')
    store.handleEvent(event('status', 5, { state: 'running', cycle: 2, reset_frame_id: 'child' }))
    expect(store.nodeStates.child).toBeUndefined()
    expect(store.nodeStates.parent.state).toBe('done')
  })

  it('replays logs once without changing a newer snapshot and clears them on a new run', () => {
    const store = useRunStore()
    store.handleEvent(event('log', 2, { text: 'first' }))
    store.handleEvent(event('status', 3, { state: 'running', node_states: { a: { state: 'done' } } }))
    store.handleEvent(event('log', 2, { text: 'first' }))
    expect(store.logs.map((log) => log.text)).toEqual(['first'])
    expect(store.nodeStates.a.state).toBe('done')
    store.handleEvent(event('status', 5, { state: 'running', node_states: {} }, 'new'))
    store.handleEvent(event('log', 2, { text: 'old' }))
    expect(store.logs).toEqual([])
  })

  it('keeps an initial log replay when status was fetched first', () => {
    const store = useRunStore()
    store.applyStatus({ seq: 10, run_id: 'run', state: 'running', node_states: {} })
    store.handleEvent(event('log', 8, { text: 'history' }))
    store.handleEvent(event('status', 10, { state: 'running', node_states: {} }))
    expect(store.logs.map((log) => log.text)).toEqual(['history'])
  })

  it('ignores duplicate finished events and stale start replies', async () => {
    const store = useRunStore()
    let resolve
    startRun.mockImplementation(() => new Promise((done) => { resolve = done }))
    const starting = store.start('preset')
    store.handleEvent(event('finished', 10, { status: 'completed', message: 'done', node_states: { a: { state: 'done' } } }))
    store.handleEvent(event('finished', 10, { status: 'completed', message: 'done' }))
    resolve({ seq: 1, run_id: 'run', state: 'running' })
    await starting
    expect(store.state).toBe('idle')
    expect(store.logs).toHaveLength(1)
    expect(store.nodeStates.a.state).toBe('done')
  })

  it('accepts backend restart sequence zero and rejects old HTTP and retired events', async () => {
    const store = useRunStore()
    store.applyStatus({ server_id: 'old', run_id: 'before', seq: 100, state: 'running' })
    let resolve
    fetchRunStatus.mockImplementation(() => new Promise((done) => { resolve = done }))
    const refreshing = store.refreshStatus()
    store.handleEvent({ server_id: 'new', run_id: null, seq: 0, type: 'status', data: { state: 'idle', node_states: {} } })
    resolve({ server_id: 'old', run_id: 'before', seq: 101, state: 'running' })
    await refreshing
    store.handleEvent({ server_id: 'old', run_id: 'before', seq: 102, type: 'status', data: { state: 'running' } })
    expect(store.serverId).toBe('new')
    expect(store.lastSeq).toBe(0)
    expect(store.state).toBe('idle')
    store.handleEvent({ server_id: 'new', run_id: 'after', seq: 1, type: 'log', data: { text: 'new history' } })
    store.handleEvent({ server_id: 'new', run_id: 'after', seq: 2, type: 'status', data: { state: 'running', node_states: {} } })
    expect(store.logs.map((log) => log.text)).toEqual(['new history'])
    expect(store.state).toBe('running')
  })

  it('indexes running steps and frame resets without enumerating historical nodes per event', () => {
    const store = useRunStore()
    store.applyStatus({ run_id: 'run', seq: 1, state: 'running', node_states: {
      ...Object.fromEntries(Array.from({ length: 2000 }, (_, i) => [`old-${i}`, { state: 'done', frame_id: 'history' }])),
      parent: { state: 'running', frame_id: 'root' },
      oldChild: { state: 'running', frame_id: 'child' },
    } })
    const enumerate = vi.spyOn(Object, 'entries')
    const before = store.nodeRevision
    store.handleEvent(event('step', 2, { step_id: 'newChild', frame_id: 'child', state: 'running' }))
    expect(enumerate).not.toHaveBeenCalled()
    expect(store.nodeChangesSince(before)).toEqual(['oldChild', 'newChild'])
    expect(store.nodeStates.parent.state).toBe('running')
    expect(store.nodeStates.oldChild.state).toBe('idle')
    store.handleEvent(event('status', 3, { state: 'running', reset_frame_id: 'child' }))
    expect(enumerate).not.toHaveBeenCalled()
    enumerate.mockRestore()
    expect(store.nodeStates.oldChild).toBeUndefined()
    expect(store.nodeStates.newChild).toBeUndefined()
    expect(store.nodeStates['old-0'].state).toBe('done')
    store.handleEvent(event('step', 4, { step_id: 'childAgain', frame_id: 'child', state: 'running' }))
    expect(store.nodeStates.childAgain.state).toBe('running')
  })

  it('keeps a bounded revision journal with full-sync fallback and reset barriers', () => {
    const store = useRunStore()
    store.handleEvent(event('step', 1, { step_id: 'a', state: 'running' }))
    const before = store.nodeRevision
    store.handleEvent(event('step', 2, { step_id: 'a', state: 'failed', message: 'boom' }))
    store.handleEvent(event('status', 3, { state: 'running', root_cycle: 2 }))
    store.handleEvent(event('step', 4, { step_id: 'b', state: 'done' }))
    expect(store.nodeChangesSince(before)).toBeNull()
    expect(store.nodeStates).toEqual({ b: { step_id: 'b', state: 'done', error: '' } })
    const checkpoint = store.nodeRevision
    for (let i = 0; i < NODE_CHANGE_LIMIT + 10; i++) store.setNodeState('b', { state: 'done', i })
    expect(runIndex(store).journal).toHaveLength(NODE_CHANGE_LIMIT)
    expect(store.nodeChangesSince(checkpoint)).toBeNull()
    expect(store.nodeChangesSince(store.nodeRevision - 1)).toEqual(['b'])
    const consumer = store.nodeRevision - 1
    expect(store.nodeChangesSince(consumer)).toEqual(store.nodeChangesSince(consumer))
  })

  it('reindexes externally replaced snapshots and preserves final failures', () => {
    const store = useRunStore()
    store.nodeStates = { root: { state: 'running', frame_id: 'root' }, failed: { state: 'failed', error: 'boom', frame_id: 'child' } }
    store.handleEvent({ type: 'step', data: { step_id: 'next', frame_id: 'root', state: 'running' } })
    expect(store.nodeStates.root.state).toBe('idle')
    store.handleEvent({ type: 'finished', data: { status: 'failed' } })
    expect(store.nodeStates.next.state).toBe('idle')
    expect(store.nodeStates.failed).toEqual({ state: 'failed', error: 'boom', frame_id: 'child' })
  })

  it('bounds dedup and finished logs, including unique unsequenced ids at capacity', () => {
    const store = useRunStore()
    store.applyStatus({ run_id: 'run', seq: 0, state: 'running' })
    const enumerate = vi.spyOn(Object, 'keys')
    for (let seq = 1; seq <= 1100; seq++) store.handleEvent(event('log', seq, { text: `${seq}`, id: 'untrusted-id' }))
    expect(enumerate).not.toHaveBeenCalled()
    enumerate.mockRestore()
    expect(runIndex(store).logIds.size).toBe(LOG_DEDUP_LIMIT)
    const newest = store.logs.at(-1).id
    store.handleEvent(event('log', 1100, { text: 'duplicate' }))
    expect(store.logs.at(-1).id).toBe(newest)
    expect(store.logs.at(-1).text).toBe('1100')
    for (let i = 0; i < 10; i++) store.handleEvent({ type: 'log', data: { text: 'legacy' } })
    store.handleEvent(event('finished', 1200, { status: 'completed' }))
    expect(store.logs).toHaveLength(500)
    expect(new Set(store.logs.map((line) => line.id)).size).toBe(500)
    expect(store.logs.at(-1).id).toContain('finished')
    store.clearLogs()
    expect(runIndex(store).logIds.size).toBe(0)
    expect(store.logs).toEqual([])
  })

  it('supports legacy unsequenced events', () => {
    const store = useRunStore()
    store.handleEvent({ type: 'step', data: { step_id: 'a', state: 'running' } })
    store.handleEvent({ type: 'finished', data: { status: 'stopped' } })
    expect(store.nodeStates.a.state).toBe('idle')
    expect(store.status).toBe('stopped')
  })
})
