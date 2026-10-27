import { defineStore } from 'pinia'
import { markRaw, toRaw } from 'vue'
import { EventSocket } from '../api/socket.js'
import { fetchRunStatus, startRun, stopRun } from '../api/run.js'
import { useDeviceStore } from './deviceStore.js'
import { changesSince, ensureNodeIndex, eventLogId, indexNode, LOG_DEDUP_LIMIT, LOG_LIMIT, recordNodeChange, runIndex } from './runUpdates.js'

export const useRunStore = defineStore('run', {
  state: () => ({
    state: 'idle', status: 'idle', presetId: null, cycle: 0, rootCycle: 0,
    stepIndex: 0, stepCount: 0, message: '', logs: markRaw([]), nodeStates: {},
    runId: null, serverId: null, retiredServers: [], lastSeq: -1, nodeRevision: 0, frames: [],
    wsState: 'disconnected', socket: null,
  }),
  getters: {
    running: (state) => ['starting', 'running', 'stopping'].includes(state.state),
  },
  actions: {
    nodeChangesSince(revision) { return changesSince(this, revision) },
    replaceNodeStates(states = {}) {
      this.nodeStates = structuredClone(states)
      ensureNodeIndex(this)
      recordNodeChange(this)
    },
    setNodeState(stepId, node) {
      const index = ensureNodeIndex(this)
      indexNode(index, stepId, this.nodeStates[stepId], true)
      if (node === undefined) delete this.nodeStates[stepId]
      else {
        this.nodeStates[stepId] = node
        indexNode(index, stepId, node)
      }
      recordNodeChange(this, stepId)
    },
    clearLogs() {
      this.logs = markRaw([])
      runIndex(this).logIds.clear()
    },
    appendLog(event, data, kind = 'log') {
      const ids = runIndex(this).logIds
      const id = eventLogId(event, kind)
      if (ids.has(id)) return
      ids.add(id)
      if (ids.size > LOG_DEDUP_LIMIT) ids.delete(ids.values().next().value)
      // Immutable catalog-sized arrays avoid triggering a reactive splice for
      // every retained row. Rows never change after publication.
      const retained = toRaw(this.logs)
      this.logs = markRaw([...retained.slice(Math.max(0, retained.length - LOG_LIMIT + 1)),
        markRaw({ ...data, id, time: data.time ?? new Date() })])
    },
    acceptServer(serverId) {
      if (serverId === undefined || serverId === this.serverId) return true
      if (this.retiredServers.includes(serverId)) return false
      if (this.serverId !== null) this.retiredServers.push(this.serverId)
      this.serverId = serverId
      this.lastSeq = -1
      this.runId = null
      this.replaceNodeStates()
      this.clearLogs()
      this.rootCycle = 0
      this.frames = []
      return true
    },
    acceptState(payload) {
      if (!this.acceptServer(payload.server_id)) return false
      const seq = payload.seq
      if (Number.isFinite(seq)) {
        if (seq <= this.lastSeq) return false
        this.lastSeq = seq
      }
      if (payload.run_id !== undefined && payload.run_id !== this.runId) {
        this.runId = payload.run_id
        this.replaceNodeStates()
        this.clearLogs()
        this.rootCycle = 0
        this.frames = []
      }
      return true
    },
    applyStatus(payload = {}) {
      if (!this.acceptState(payload)) return
      const nextState = payload.state || payload.status || 'idle'
      if (payload.node_states) this.replaceNodeStates(payload.node_states)
      else if (payload.root_cycle != null && payload.root_cycle !== this.rootCycle) this.replaceNodeStates()
      if (!payload.node_states && payload.reset_frame_id) {
        const members = ensureNodeIndex(this).frames.get(payload.reset_frame_id)
        for (const id of [...(members || [])]) this.setNodeState(id, undefined)
      }
      this.state = nextState
      this.status = payload.status || payload.last_status || nextState
      if ('preset_id' in payload) this.presetId = payload.preset_id
      this.cycle = payload.cycle ?? this.cycle
      this.rootCycle = payload.root_cycle ?? this.rootCycle
      this.stepIndex = payload.step_index ?? this.stepIndex
      this.stepCount = payload.step_count ?? this.stepCount
      this.message = payload.message ?? payload.last_message ?? this.message
      this.frames = payload.frames ?? this.frames
    },
    handleEvent(event) {
      if (!event) return
      const data = event.data || {}
      if (!this.acceptServer(event.server_id)) return
      const meta = { server_id: event.server_id, run_id: event.run_id, seq: event.seq }
      if (event.type === 'log') {
        if (event.run_id !== undefined && event.run_id !== this.runId) {
          if (Number.isFinite(event.seq) && event.seq <= this.lastSeq) return
          this.acceptState({ run_id: event.run_id })
        }
        this.appendLog(event, data)
      } else if (event.type === 'status') {
        this.applyStatus({ ...data, ...meta })
      } else if (event.type === 'step') {
        if (!this.acceptState(meta) || !data.step_id) return
        if (data.state === 'running') {
          const running = ensureNodeIndex(this).running.get(data.frame_id)
          for (const stepId of [...(running || [])]) {
            if (stepId !== data.step_id) this.setNodeState(stepId, { ...this.nodeStates[stepId], state: 'idle' })
          }
        }
        this.setNodeState(data.step_id, { ...data, state: data.state || 'idle', error: data.error || data.message || '' })
      } else if (event.type === 'finished') {
        if (!this.acceptState(meta)) return
        if (data.node_states) this.replaceNodeStates(data.node_states)
        const running = [...ensureNodeIndex(this).running.values()].flatMap((ids) => [...ids])
        for (const stepId of running) this.setNodeState(stepId, { ...this.nodeStates[stepId], state: 'idle' })
        this.state = 'idle'
        this.status = data.status || 'completed'
        this.message = data.message || ''
        this.presetId = null
        this.cycle = 0
        this.stepIndex = 0
        this.stepCount = 0
        this.frames = []
        this.appendLog(event, { text: data.message || `运行${data.status || '结束'}`, level: data.status }, 'finished')
      } else if (event.type === 'device') {
        useDeviceStore().apply(data)
      }
    },
    connect(onReconnect) {
      if (this.socket) return
      this.socket = new EventSocket({
        onEvent: (event) => this.handleEvent(event),
        onState: (state) => { this.wsState = state },
        onReconnect: () => { onReconnect?.() },
      })
      this.socket.connect()
    },
    async refreshStatus() {
      const serverId = this.serverId
      const payload = await fetchRunStatus()
      if (serverId !== this.serverId && payload.server_id !== this.serverId) return
      this.applyStatus(payload)
    },
    async start(presetId) {
      this.replaceNodeStates()
      this.clearLogs()
      this.applyStatus({ state: 'running', preset_id: presetId, cycle: 1 })
      const serverId = this.serverId
      try {
        const result = await startRun(presetId)
        if (result && typeof result === 'object' && (serverId === this.serverId || result.server_id === this.serverId)) this.applyStatus(result)
      } catch (error) {
        this.state = 'idle'
        throw error
      }
    },
    async stop() {
      this.state = 'stopping'
      this.message = '已请求停止，等待当前 ADB 命令结束'
      const serverId = this.serverId
      const result = await stopRun()
      if (result && typeof result === 'object' && (serverId === this.serverId || result.server_id === this.serverId)) this.applyStatus(result)
    },
  },
})
