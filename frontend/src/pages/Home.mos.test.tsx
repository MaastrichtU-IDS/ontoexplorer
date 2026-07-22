import { describe, it, expect } from 'vitest'
import { normalizeMos, isNamedClassQuery } from './Home'

describe('normalizeMos', () => {
  it('quotes a bare multi-word label', () => {
    expect(normalizeMos('catalytic activity')).toBe("'catalytic activity'")
    expect(normalizeMos('  regulation of catabolic process ')).toBe("'regulation of catabolic process'")
  })

  it('leaves a single token untouched', () => {
    expect(normalizeMos('cell')).toBe('cell')
    expect(normalizeMos('GO:0008150')).toBe('GO:0008150')
  })

  it('leaves an already-quoted phrase untouched', () => {
    expect(normalizeMos("'cell death'")).toBe("'cell death'")
  })

  it('leaves a genuine expression untouched (operator token)', () => {
    expect(normalizeMos('cell and nucleus')).toBe('cell and nucleus')
    expect(normalizeMos("'has part' some cell")).toBe("'has part' some cell")
  })

  it('leaves anything with parens untouched', () => {
    expect(normalizeMos('a and (b or c)')).toBe('a and (b or c)')
  })

  it('handles empty/whitespace', () => {
    expect(normalizeMos('')).toBe('')
    expect(normalizeMos('   ')).toBe('')
  })
})

describe('isNamedClassQuery (on normalized input)', () => {
  it('is true for a bare multi-word label once normalized', () => {
    expect(isNamedClassQuery(normalizeMos('catalytic activity'))).toBe(true)
  })

  it('is true for a single token or CURIE', () => {
    expect(isNamedClassQuery('cell')).toBe(true)
    expect(isNamedClassQuery('GO:0008150')).toBe(true)
  })

  it('is true for a quoted phrase', () => {
    expect(isNamedClassQuery("'cell death'")).toBe(true)
  })

  it('is false for a complex expression', () => {
    expect(isNamedClassQuery(normalizeMos("'has part' some cell"))).toBe(false)
    expect(isNamedClassQuery(normalizeMos('cell and nucleus'))).toBe(false)
  })

  it('is false for empty', () => {
    expect(isNamedClassQuery('')).toBe(false)
  })
})
