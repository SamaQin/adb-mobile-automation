import { defineStore } from 'pinia'
import { EventSocket } from '../api/socket.js'
import { fetchRunStatus, startRun, stopRun } from '../api/run.js'
import { useDeviceStore } from './deviceStore.js'

export const useRunStore = defineStore('run', {
  state: () => ({
    state: 'idle',
    status: 'idle',
    presetId: null,
    cycle: 0,
    stepIndex: 0,
    stepCount: 0,
    message: '',
    logs: [],
    nodeStates: {},
    wsState: 'disconnected',
    socket: null,
  }),
  getters: {
    running: (state) => ['starting', 'running', 'stopping'].includes(state.state),
  },
  actions: {
    applyStatus(payload = {}) {
      const nextState = payload.state || payload.status || 'idle'
      if (payload.cycle && payload.cycle !== this.cycle) this.nodeStates = {}
      this.state = nextState
      this.status = payload.status || nextState
      this.presetId = payload.preset_id ?? this.presetId
      this.cycle = payload.cycle ?? this.cycle
      this.stepIndex = payload.step_index ?? this.stepIndex
      this.stepCount = payload.step_count ?? this.stepCount
      this.message = payload.message ?? this.message
    },
    handleEvent(event) {
      const data = event?.data || {}
      if (event.type === 'log') {
        this.logs.push({ id: `${Date.now()}-${this.logs.length}`, time: new Date(), ...data })
        if (this.logs.length > 500) this.logs.shift()
      } else if (event.type === 'status') {
        this.applyStatus(data)
      } else if (event.type === 'step') {
        if (data.state === 'running') {
          for (const [stepId, state] of Object.entries(this.nodeStates)) {
            if (state?.state === 'running') this.nodeStates[stepId] = { ...state, state: 'idle' }
          }
        }
        this.nodeStates[data.step_id] = { state: data.state || 'idle', error: data.error || data.message || '' }
      } else if (event.type === 'finished') {
        for (const [stepId, state] of Object.entries(this.nodeStates)) {
          if (state?.state === 'running') this.nodeStates[stepId] = { ...state, state: 'idle' }
        }
        this.state = 'idle'
        this.status = data.status || 'completed'
        this.message = data.message || ''
        this.logs.push({ id: `${Date.now()}-finished`, time: new Date(), text: data.message || `运行${data.status || '结束'}`, level: data.status })
      } else if (event.type === 'device') {
        useDeviceStore().apply(data)
      }
    },
    connect(onReconnect) {
      if (this.socket) return
      this.socket = new EventSocket({
        onEvent: (event) => this.handleEvent(event),
        onState: (state) => { this.wsState = state },
        onReconnect: async () => {
          await this.refreshStatus().catch(() => {})
          onReconnect?.()
        },
      })
      this.socket.connect()
    },
    async refreshStatus() {
      this.applyStatus(await fetchRunStatus())
    },
    async start(presetId) {
      this.nodeStates = {}
      this.logs = []
      this.applyStatus({ state: 'running', preset_id: presetId, cycle: 1 })
      try {
        const result = await startRun(presetId)
        if (result && typeof result === 'object') this.applyStatus(result)
      } catch (error) {
        this.state = 'idle'
        throw error
      }
    },
    async stop() {
      this.state = 'stopping'
      this.message = '已请求停止，等待当前 ADB 命令结束'
      await stopRun()
    },
  },
})
