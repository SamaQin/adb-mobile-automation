import { defineStore } from 'pinia'

export const useUiStore = defineStore('ui', {
  state: () => ({
    readOnly: false,
    selectedNodeIds: [],
    selectedEdgeId: null,
    templateDrawerOpen: false,
    paletteCollapsed: false,
    propertiesCollapsed: false,
    logCollapsed: false,
    toast: null,
    screenshotRequest: null,
    jsonDialog: null,
  }),
  getters: {
    selectedNodeId: (state) => state.selectedNodeIds.length === 1 ? state.selectedNodeIds[0] : null,
  },
  actions: {
    notify(message, tone = 'info') {
      this.toast = { id: Date.now(), message, tone }
      window.clearTimeout(this.toastTimer)
      this.toastTimer = window.setTimeout(() => { this.toast = null }, 3200)
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
