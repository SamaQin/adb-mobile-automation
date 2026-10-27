import { defineStore } from 'pinia'

const pendingDialogs = new WeakMap()

export const useUiStore = defineStore('ui', {
  state: () => ({
    readOnly: false,
    selectedNodeIds: [],
    selectedEdgeId: null,
    templateDrawerOpen: false,
    deviceMonitorOpen: false,
    paletteCollapsed: false,
    propertiesCollapsed: false,
    logCollapsed: false,
    toast: null,
    screenshotRequest: null,
    jsonDialog: null,
    dialog: null,
    helpOpen: false,
  }),
  getters: {
    selectedNodeId: (state) => state.selectedNodeIds.length === 1 ? state.selectedNodeIds[0] : null,
  },
  actions: {
    notify(message, tone = 'info', action = null) {
      this.toast = { id: Date.now(), message, tone, action }
      window.clearTimeout(this.toastTimer)
      this.toastTimer = window.setTimeout(() => { this.toast = null }, action ? 8000 : tone === 'error' ? 7000 : 3600)
    },
    resolveDialog(result = null) {
      const resolve = pendingDialogs.get(this)
      pendingDialogs.delete(this)
      this.dialog = null
      resolve?.(result)
    },
    promptText(options) {
      this.resolveDialog(null)
      return new Promise((resolve) => {
        pendingDialogs.set(this, resolve)
        this.dialog = { ...options, kind: 'prompt' }
      })
    },
    async confirmAction(options) {
      this.resolveDialog(null)
      const result = await new Promise((resolve) => {
        pendingDialogs.set(this, resolve)
        this.dialog = { ...options, kind: 'confirm' }
      })
      return result === true
    },
    selectNode(id, additive = false) {
      this.selectedEdgeId = null
      if (!additive) this.selectedNodeIds = id ? [id] : []
      else if (this.selectedNodeIds.includes(id)) this.selectedNodeIds = this.selectedNodeIds.filter((item) => item !== id)
      else this.selectedNodeIds.push(id)
    },
    selectEdge(id) {
      this.selectedNodeIds = []
      this.selectedEdgeId = id
    },
    clearSelection() {
      this.selectedNodeIds = []
      this.selectedEdgeId = null
    },
    openScreenshot(request) {
      this.screenshotRequest = request
    },
    closeScreenshot(result = null) {
      this.screenshotRequest?.resolve?.(result)
      this.screenshotRequest = null
    },
  },
})
