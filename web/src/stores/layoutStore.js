import { defineStore } from 'pinia'
import { autoLayoutForPreset } from '../composables/useAutoLayout.js'
import { cloneJson } from '../utils/clone.js'

const GROUPS_KEY = '__groups'
const GROUP_OF_KEY = '__groupOf'
const NODE_WIDTH = 242
const NODE_HEIGHT = 116
const GROUP_PADDING_X = 34
const GROUP_PADDING_TOP = 50
const GROUP_PADDING_BOTTOM = 30
const LAYOUT_VERSION = 2

function newLayoutId() {
  const random = globalThis.crypto?.randomUUID?.()
  return (random || `${Date.now()}-${Math.random()}`).replaceAll('-', '')
}

function storageKey(presetId) {
  return `layout:${presetId}`
}

function readLayout(presetId) {
  try {
    const layout = JSON.parse(localStorage.getItem(storageKey(presetId)) || '{}')
    return layout.__layoutVersion === LAYOUT_VERSION ? layout : { __layoutVersion: LAYOUT_VERSION }
  } catch {
    return { __layoutVersion: LAYOUT_VERSION }
  }
}

function groupBounds(memberIds, layout, fallback) {
  const positions = memberIds.map((id) => layout[id]).filter(Boolean)
  if (!positions.length) return fallback
  const minX = Math.min(...positions.map((position) => position.x))
  const minY = Math.min(...positions.map((position) => position.y))
  const maxX = Math.max(...positions.map((position) => position.x + NODE_WIDTH))
  const maxY = Math.max(...positions.map((position) => position.y + NODE_HEIGHT))
  return {
    x: minX - GROUP_PADDING_X,
    y: minY - GROUP_PADDING_TOP,
    width: Math.max(320, maxX - minX + GROUP_PADDING_X * 2),
    height: Math.max(220, maxY - minY + GROUP_PADDING_TOP + GROUP_PADDING_BOTTOM),
  }
}

function syncGroupBounds(layout) {
  const groups = layout[GROUPS_KEY] || {}
  const groupOf = layout[GROUP_OF_KEY] || {}
  for (const group of Object.values(groups)) {
    const members = Object.entries(groupOf)
      .filter(([, groupId]) => groupId === group.id)
      .map(([nodeId]) => nodeId)
    Object.assign(group, groupBounds(members, layout, group))
  }
}

export const useLayoutStore = defineStore('layout', {
  state: () => ({ layouts: {}, revision: 0 }),
  actions: {
    load(presetId) {
      if (!this.layouts[presetId]) this.layouts[presetId] = readLayout(presetId)
      return this.layouts[presetId]
    },
    get(presetId) {
      return this.load(presetId)
    },
    persist(presetId) {
      this.layouts[presetId].__layoutVersion = LAYOUT_VERSION
      localStorage.setItem(storageKey(presetId), JSON.stringify(this.layouts[presetId] || {}))
      this.revision += 1
    },
    setPosition(presetId, nodeId, position) {
      const layout = this.load(presetId)
      layout[nodeId] = { x: Number(position.x), y: Number(position.y) }
      this.persist(presetId)
    },
    setLayout(presetId, layout) {
      this.layouts[presetId] = cloneJson(layout)
      this.persist(presetId)
    },
    groups(presetId) {
      const layout = this.load(presetId)
      layout[GROUPS_KEY] ||= {}
      return Object.values(layout[GROUPS_KEY])
    },
    createGroup(presetId, name, nodeIds = [], flowNodes = []) {
      const layout = this.load(presetId)
      layout[GROUPS_KEY] ||= {}
      layout[GROUP_OF_KEY] ||= {}
      for (const node of flowNodes) {
        if (node.id !== 'start' && !node.id.startsWith('group:')) {
          layout[node.id] = { x: Number(node.position.x), y: Number(node.position.y) }
        }
      }
      const id = `group:${newLayoutId()}`
      const fallback = { x: 120, y: 120, width: 420, height: 300 }
      const group = { id, name: name || '新泳道', color: '#38bdf8', ...groupBounds(nodeIds, layout, fallback) }
      layout[GROUPS_KEY][id] = group
      for (const nodeId of nodeIds) layout[GROUP_OF_KEY][nodeId] = id
      this.persist(presetId)
      return group
    },
    removeGroup(presetId, groupId) {
      const layout = this.load(presetId)
      delete layout[GROUPS_KEY]?.[groupId]
      for (const [nodeId, owner] of Object.entries(layout[GROUP_OF_KEY] || {})) {
        if (owner === groupId) delete layout[GROUP_OF_KEY][nodeId]
      }
      this.persist(presetId)
    },
    renameGroup(presetId, groupId, name) {
      const group = this.load(presetId)[GROUPS_KEY]?.[groupId]
      if (!group || !name.trim()) return
      group.name = name.trim()
      this.persist(presetId)
    },
    assignNodeToGroup(presetId, nodeId, position) {
      const layout = this.load(presetId)
      layout[GROUPS_KEY] ||= {}
      layout[GROUP_OF_KEY] ||= {}
      layout[nodeId] = { x: Number(position.x), y: Number(position.y) }
      const center = { x: position.x + NODE_WIDTH / 2, y: position.y + NODE_HEIGHT / 2 }
      const owner = Object.values(layout[GROUPS_KEY]).find((group) => (
        center.x >= group.x
        && center.x <= group.x + group.width
        && center.y >= group.y
        && center.y <= group.y + group.height
      ))
      if (owner) layout[GROUP_OF_KEY][nodeId] = owner.id
      else delete layout[GROUP_OF_KEY][nodeId]
      syncGroupBounds(layout)
      this.persist(presetId)
    },
    moveGroup(presetId, groupId, position) {
      const layout = this.load(presetId)
      const group = layout[GROUPS_KEY]?.[groupId]
      if (!group) return
      const deltaX = Number(position.x) - group.x
      const deltaY = Number(position.y) - group.y
      group.x = Number(position.x)
      group.y = Number(position.y)
      for (const [nodeId, owner] of Object.entries(layout[GROUP_OF_KEY] || {})) {
        if (owner !== groupId || !layout[nodeId]) continue
        layout[nodeId] = {
          x: layout[nodeId].x + deltaX,
          y: layout[nodeId].y + deltaY,
        }
      }
      this.persist(presetId)
    },
    autoLayout(preset) {
      const current = this.load(preset.id)
      const layout = {
        ...autoLayoutForPreset(preset),
        [GROUPS_KEY]: cloneJson(current[GROUPS_KEY] || {}),
        [GROUP_OF_KEY]: cloneJson(current[GROUP_OF_KEY] || {}),
      }
      syncGroupBounds(layout)
      this.setLayout(preset.id, layout)
      return layout
    },
    reset(presetId) {
      delete this.layouts[presetId]
      localStorage.removeItem(storageKey(presetId))
    },
  },
})
