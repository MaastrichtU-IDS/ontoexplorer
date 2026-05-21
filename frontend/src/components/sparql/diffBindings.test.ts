import { describe, it, expect } from 'vitest'
import { canonicalRow, diffBindings, BindingRow, BindingValue } from './diffBindings'

const uri = (v: string): BindingValue => ({ type: 'uri', value: v })
const lit = (v: string, lang?: string, datatype?: string): BindingValue =>
  ({ type: 'literal', value: v, ...(lang ? { 'xml:lang': lang } : {}), ...(datatype ? { datatype } : {}) })

describe('canonicalRow', () => {
  it('produces the same string regardless of insertion order', () => {
    const a: BindingRow = { x: uri('http://a/'), y: lit('foo') }
    const b: BindingRow = { y: lit('foo'), x: uri('http://a/') }
    expect(canonicalRow(a)).toBe(canonicalRow(b))
  })

  it('distinguishes URI from literal with the same value', () => {
    expect(canonicalRow({ x: uri('foo') })).not.toBe(canonicalRow({ x: lit('foo') }))
  })

  it('distinguishes literals with different language tags', () => {
    expect(canonicalRow({ x: lit('foo', 'en') })).not.toBe(canonicalRow({ x: lit('foo', 'de') }))
  })

  it('distinguishes literals with different datatypes', () => {
    expect(canonicalRow({ x: lit('1', undefined, 'http://www.w3.org/2001/XMLSchema#integer') }))
      .not.toBe(canonicalRow({ x: lit('1') }))
  })

  it('treats a missing variable as different from a present-but-empty one', () => {
    expect(canonicalRow({ x: uri('a') })).not.toBe(canonicalRow({ x: uri('a'), y: lit('') }))
  })
})

describe('diffBindings', () => {
  it('returns all-Both when sides are identical', () => {
    const rows: BindingRow[] = [{ x: uri('a') }, { x: uri('b') }]
    const result = diffBindings(rows, rows)
    expect(result.onlyFrom).toEqual([])
    expect(result.onlyTo).toEqual([])
    expect(result.both).toHaveLength(2)
  })

  it('returns all-onlyFrom + all-onlyTo when sides are disjoint', () => {
    const from: BindingRow[] = [{ x: uri('a') }]
    const to: BindingRow[] = [{ x: uri('b') }]
    const result = diffBindings(from, to)
    expect(result.onlyFrom).toEqual(from)
    expect(result.onlyTo).toEqual(to)
    expect(result.both).toEqual([])
  })

  it('partitions correctly for overlapping sides', () => {
    const from: BindingRow[] = [{ x: uri('a') }, { x: uri('b') }, { x: uri('c') }]
    const to:   BindingRow[] = [{ x: uri('b') }, { x: uri('c') }, { x: uri('d') }]
    const result = diffBindings(from, to)
    expect(result.onlyFrom).toEqual([{ x: uri('a') }])
    expect(result.onlyTo).toEqual([{ x: uri('d') }])
    expect(result.both).toHaveLength(2)
  })

  it('preserves From-side ordering for Both rows', () => {
    const from: BindingRow[] = [{ x: uri('c') }, { x: uri('a') }, { x: uri('b') }]
    const to:   BindingRow[] = [{ x: uri('a') }, { x: uri('b') }, { x: uri('c') }]
    const { both } = diffBindings(from, to)
    expect(both.map(r => (r.x as { value: string }).value)).toEqual(['c', 'a', 'b'])
  })

  it('returns the union of variable names in vars', () => {
    const from: BindingRow[] = [{ x: uri('a') }]
    const to:   BindingRow[] = [{ y: uri('b') }]
    const result = diffBindings(from, to)
    expect(new Set(result.vars)).toEqual(new Set(['x', 'y']))
  })

  it('handles empty sides', () => {
    expect(diffBindings([], [])).toEqual({ onlyFrom: [], onlyTo: [], both: [], vars: [] })
  })
})
