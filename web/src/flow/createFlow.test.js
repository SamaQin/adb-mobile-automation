import { describe, expect, it } from 'vitest'
import { createFlow, flowToPreset, normalizeDependencies } from './createFlow.js'

const definitions = [
  { key: 'wait', label: '等待', fields: [] },
  { key: 'find_and_tap', label: '识别并点击', fields: [] },
]

function fixture() {
  return {
    id: 'preset-1',
    name: '测试流程',
    loop_count: 2,
    steps: [
      { id: 'a', name: '第一步', kind: 'wait', enabled: true, on_failure: 'stop', depends_on: [], params: { seconds: 1 } },
      {
        id: 'b',
        name: '识别',
        kind: 'find_and_tap',
        enabled: true,
        on_failure: 'continue',
        depends_on: ['a'],
        params: {
          templates: [{ file: 'one.png', threshold: 0.8 }, { file: 'two.png', threshold: 0.7 }],
          branches: {
            1: [
              { id: 'c', name: '分支等待', kind: 'wait', enabled: true, on_failure: 'stop', depends_on: [], params: { seconds: 2 } },
              { id: 'd', name: '分支二', kind: 'wait', enabled: true, on_failure: 'stop', depends_on: ['c'], params: { seconds: 3, return_to: 'a' } },
            ],
          },
        },
      },
      { id: 'e', name: '默认后续', kind: 'wait', enabled: true, on_failure: 'stop', depends_on: [], params: { seconds: 4, return_to: 'a' } },
    ],
  }
}

describe('createFlow', () => {
  it('derives start/order/dependency and branch nodes without changing config', () => {
    const preset = fixture()
    const before = structuredClone(preset)
    const { nodes, edges } = createFlow(preset, definitions)

    expect(nodes.map((node) => node.id)).toEqual(['start', 'a', 'b', 'branch:b:1:c', 'branch:b:1:d', 'e'])
    expect(nodes.find((node) => node.id === 'b').data.order).toBe(2)
    expect(nodes.find((node) => node.id === 'branch:b:1:c').data.branch.label).toBe('two.png')
    expect(edges.some((edge) => edge.source === 'start' && edge.target === 'a' && edge.data.kind === 'order')).toBe(true)
    expect(edges.some((edge) => edge.source === 'a' && edge.target === 'b' && edge.data.kind === 'dependency' && edge.sourceHandle === 'dependency-source')).toBe(true)
    expect(edges.some((edge) => edge.source === 'a' && edge.target === 'e' && edge.data.kind === 'order' && edge.sourceHandle === 'order-source')).toBe(true)
    expect(edges.some((edge) => edge.sourceHandle === 'branch-1' && edge.target === 'branch:b:1:c')).toBe(true)
    expect(edges.some((edge) => edge.source === 'branch:b:1:c' && edge.target === 'branch:b:1:d' && edge.sourceHandle === 'dependency-source')).toBe(true)
    expect(nodes.find((node) => node.id === 'a').data.outgoingDependencyCount).toBe(1)
    const start = nodes.find((node) => node.id === 'start')
    const firstMain = nodes.find((node) => node.id === 'a')
    expect(start.position.x + 88 / 2).toBe(firstMain.position.x + 242 / 2)
    expect(nodes.find((node) => node.id === 'b').position.x).toBeGreaterThan(nodes.find((node) => node.id === 'a').position.x)
    expect(nodes.find((node) => node.id === 'b').position.y).toBe(nodes.find((node) => node.id === 'a').position.y)
    expect(edges.some((edge) => edge.source === 'e' && edge.target === 'a' && edge.data.kind === 'return' && edge.sourceHandle === 'order-source')).toBe(true)
    expect(nodes.find((node) => node.id === 'e').data.returnTargetName).toBe('第一步')
    expect(edges.some((edge) => edge.source === 'branch:b:1:d' && edge.target === 'a' && edge.data.kind === 'return')).toBe(true)
    expect(nodes.find((node) => node.id === 'branch:b:1:d').data.returnTargetName).toBe('第一步')
    expect(preset).toEqual(before)
  })

  it('round-trips order, dependencies and recursive branch payloads', () => {
    const preset = fixture()
    const flow = createFlow(preset, definitions)
    const result = flowToPreset(preset, flow.nodes, flow.edges)

    expect(result).toEqual(preset)
    expect(result.steps[1].params.branches['1'][1].depends_on).toEqual(['c'])
    expect(result.steps[2].params.return_to).toBe('a')
  })

  it('drops return targets that are no longer valid after normalization', () => {
    const preset = fixture()
    preset.steps[2].params.return_to = 'e'
    normalizeDependencies(preset.steps)
    expect(preset.steps[2].params.return_to).toBeUndefined()
    const flow = createFlow(preset, definitions)
    expect(flow.edges.some((edge) => edge.source === 'e' && edge.data.kind === 'return')).toBe(false)
    expect(flow.edges.some((edge) => edge.source === 'branch:b:1:d' && edge.data.kind === 'return')).toBe(true)
  })

  it('uses persisted positions while keeping array order authoritative', () => {
    const preset = fixture()
    const flow = createFlow(preset, definitions, { start: { x: 410, y: 90 }, a: { x: 900, y: 500 }, b: { x: 20, y: 20 } })
    expect(flow.nodes.find((node) => node.id === 'start').position).toEqual({ x: 410, y: 90 })
    expect(flow.nodes.find((node) => node.id === 'a').position).toEqual({ x: 900, y: 500 })
    expect(flow.nodes.find((node) => node.id === 'a').data.order).toBe(1)
    expect(flow.nodes.find((node) => node.id === 'b').data.order).toBe(2)
  })
})
