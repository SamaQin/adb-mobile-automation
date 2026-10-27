export class EventSocket {
  constructor({ onEvent, onState, onReconnect }) {
    this.onEvent = onEvent
    this.onState = onState
    this.onReconnect = onReconnect
    this.socket = null
    this.timer = null
    this.closed = false
    this.attempt = 0
  }

  connect() {
    this.closed = false
    clearTimeout(this.timer)
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws/events`)
    this.socket = socket
    this.onState?.('connecting')

    socket.addEventListener('open', () => {
      const wasReconnect = this.attempt > 0
      this.attempt = 0
      this.onState?.('connected')
      if (wasReconnect) this.onReconnect?.()
    })
    socket.addEventListener('message', (event) => {
      try {
        this.onEvent?.(JSON.parse(event.data))
      } catch {
        this.onEvent?.({ type: 'log', data: { text: String(event.data) } })
      }
    })
    socket.addEventListener('close', () => {
      if (this.socket === socket) this.scheduleReconnect()
    })
    socket.addEventListener('error', () => socket.close())
  }

  scheduleReconnect() {
    if (this.closed) return
    this.attempt += 1
    this.onState?.('disconnected')
    this.socket = null
    const delay = Math.min(1000 * 2 ** (this.attempt - 1), 15000)
    clearTimeout(this.timer)
    this.timer = setTimeout(() => this.connect(), delay)
  }

  close() {
    this.closed = true
    clearTimeout(this.timer)
    this.socket?.close()
    this.socket = null
  }
}
