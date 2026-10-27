import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { EventSocket } from './socket.js'

class FakeSocket {
  static instances = []
  constructor() { this.listeners = {}; FakeSocket.instances.push(this) }
  addEventListener(name, callback) { this.listeners[name] = callback }
  emit(name, data = {}) { this.listeners[name]?.(data) }
  close() { this.emit('close') }
}
beforeEach(() => { vi.useFakeTimers(); FakeSocket.instances = []; vi.stubGlobal('WebSocket', FakeSocket) })
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

describe('event socket reconnect', () => {
  it('ignores stale connection messages and does not reconnect after explicit close', () => {
    const onEvent = vi.fn()
    const onReconnect = vi.fn()
    const client = new EventSocket({ onEvent, onReconnect })
    client.connect()
    const first = FakeSocket.instances[0]
    first.emit('open')
    first.emit('close')
    vi.advanceTimersByTime(1000)
    const second = FakeSocket.instances[1]
    first.emit('message', { data: '{"type":"finished"}' })
    first.emit('open')
    expect(onEvent).not.toHaveBeenCalled()
    second.emit('open')
    expect(onReconnect).toHaveBeenCalledTimes(1)
    second.emit('message', { data: '{"type":"status","seq":2}' })
    expect(onEvent).toHaveBeenCalledWith({ type: 'status', seq: 2 })
    client.close()
    second.emit('message', { data: '{"type":"finished"}' })
    vi.runAllTimers()
    expect(FakeSocket.instances).toHaveLength(2)
    expect(onEvent).toHaveBeenCalledTimes(1)
  })

  it('parses legacy text without swallowing handler errors as duplicate logs', () => {
    const onEvent = vi.fn()
    const client = new EventSocket({ onEvent })
    client.connect()
    const socket = FakeSocket.instances[0]
    socket.emit('message', { data: 'legacy text' })
    expect(onEvent).toHaveBeenCalledWith({ type: 'log', data: { text: 'legacy text' } })
    onEvent.mockImplementation(() => { throw new Error('consumer') })
    expect(() => socket.emit('message', { data: '{"type":"status"}' })).toThrow('consumer')
    expect(onEvent).toHaveBeenCalledTimes(2)
    client.close()
  })
})
