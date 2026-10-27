import { describe, expect, it } from 'vitest'
import { dependencyEdge, validateConnection } from './connections.js'

const nodes = [
  { id: 'start', data: { order: 0 } },
  { id: 'a', data: { order: 1 } },
  { id: 'b', data: { order: 2 } },
  { id: 'c', data: { order: 3 } },
  { id: 'p', data: { order: 4, step: { depends_on: [] } } },
  { id: 'branch:p:0:x', data: { order: 1, branch: { parentStepId: 'p', index: '0' } } },
  { id: 'branch:p:0:y', data: { order: 2, branch: { parentStepId: 'p', index: '0' } } },
  { id: 'branch:p:1:z', data: { order: 2, branch: { parentStepId: 'p', index: '1' } } },
]

describe('connection validation', () => {
  it('accepts an earlier main step dependency', () => {
    expect(validateConnection({ source: 'a', target: 'c' }, nodes, [])).toEqual({ valid: true })
    expect(dependencyEdge('a', 'c')).toMatchObject({ sourceHandle: 'dependency-source', targetHandle: 'order-target' })
  })

  it('rejects reverse, duplicate and cyclic connections', () => {
    expect(validateConnection({ source: 'c', target: 'a' }, nodes, []).reason).toMatch('更早')
    const edges = [{ source: 'a', target: 'b', data: { kind: 'dependency' } }]
    expect(validateConnection({ source: 'a', target: 'b' }, nodes, edges).duplicate).toBe(true)
    expect(validateConnection({ source: 'b', target: 'c' }, nodes, [{ source: 'c', target: 'b', data: { kind: 'dependency' } }]).valid).toBe(false)
    expect(validateConnection(
      { id: 'dependency:a:b', source: 'a', target: 'b' },
      nodes,
      [{ id: 'dependency:a:b', source: 'a', target: 'b', data: { kind: 'dependency' } }],
    ).valid).toBe(true)
  })

  it('keeps branch and main lanes isolated', () => {
    expect(validateConnection({ source: 'a', target: 'branch:p:0:y' }, nodes, []).reason).toMatch('主流程')
    expect(validateConnection({ source: 'branch:p:0:x', target: 'branch:p:1:z' }, nodes, []).reason).toMatch('不同分支')
    expect(validateConnection({ source: 'branch:p:0:x', target: 'branch:p:0:y' }, nodes, []).valid).toBe(true)
  })

  it('accepts valid start, order and template branch links', () => {
    expect(validateConnection({ source: 'start', target: 'a', sourceHandle: 'order-source' }, nodes, []).valid).toBe(true)
    expect(validateConnection({ source: 'a', target: 'b', sourceHandle: 'order-source' }, nodes, []).valid).toBe(true)
    expect(validateConnection({ source: 'p', target: 'branch:p:0:x', sourceHandle: 'branch-0' }, nodes, []).valid).toBe(true)
    expect(validateConnection({ source: 'p', target: 'branch:p:1:z', sourceHandle: 'branch-0' }, nodes, []).reason).toMatch('自身分支')
  })

  it('accepts backward order-source links as return edges', () => {
    expect(validateConnection({ source: 'c', target: 'a', sourceHandle: 'order-source' }, nodes, []).valid).toBe(true)
    expect(validateConnection({ source: 'a', target: 'c', sourceHandle: 'order-source' }, nodes, []).valid).toBe(true)
    const existing = [{ source: 'c', target: 'a', data: { kind: 'return' } }]
    expect(validateConnection({ source: 'c', target: 'a', sourceHandle: 'order-source' }, nodes, existing).duplicate).toBe(true)
    expect(validateConnection({ source: 'branch:p:0:y', target: 'branch:p:0:x', sourceHandle: 'order-source' }, nodes, []).valid).toBe(true)
  })

  it('allows branch steps to return to any main step', () => {
    expect(validateConnection({ source: 'branch:p:0:y', target: 'a', sourceHandle: 'order-source' }, nodes, []).valid).toBe(true)
    expect(validateConnection({ source: 'branch:p:0:y', target: 'p', sourceHandle: 'order-source' }, nodes, []).valid).toBe(true)
    expect(validateConnection({ source: 'a', target: 'branch:p:0:x', sourceHandle: 'order-source' }, nodes, []).valid).toBe(false)
    expect(validateConnection({ source: 'branch:p:0:y', target: 'branch:p:1:z', sourceHandle: 'order-source' }, nodes, []).reason).toMatch('不同分支')
  })
})
