import { describe, it, expect } from 'vitest'
import { classifyPosition } from './positionUtils'

const NO_PREFIXES = {}
const PREFIXES = { pizza: 'https://w3id.org/ontostart/pizza/', owl: 'http://www.w3.org/2002/07/owl#' }

describe('classifyPosition', () => {
  it('returns iri for a token starting with <', () => {
    expect(classifyPosition({ string: '<http://example.org/Marg', type: null }, NO_PREFIXES))
      .toEqual({ kind: 'iri', partial: 'http://example.org/Marg' })
  })

  it('returns iri for a bare < token (cursor just after <)', () => {
    expect(classifyPosition({ string: '<', type: null }, NO_PREFIXES))
      .toEqual({ kind: 'iri', partial: '' })
  })

  it('returns curie when token is prefix:local with known prefix', () => {
    expect(classifyPosition({ string: 'pizza:Marg', type: 'string-2' }, PREFIXES))
      .toEqual({ kind: 'curie', partial: 'Marg', prefix: 'pizza', baseIri: 'https://w3id.org/ontostart/pizza/' })
  })

  it('returns curie when token is just prefix: (empty local part)', () => {
    expect(classifyPosition({ string: 'pizza:', type: 'string-2' }, PREFIXES))
      .toEqual({ kind: 'curie', partial: '', prefix: 'pizza', baseIri: 'https://w3id.org/ontostart/pizza/' })
  })

  it('returns curie with no baseIri when prefix is unknown', () => {
    expect(classifyPosition({ string: 'unknown:Foo', type: 'string-2' }, PREFIXES))
      .toEqual({ kind: 'curie', partial: 'Foo', prefix: 'unknown' })
  })

  it('returns none for a variable token', () => {
    expect(classifyPosition({ string: '?x', type: null }, PREFIXES))
      .toEqual({ kind: 'none' })
  })

  it('returns none for a dollar-variable', () => {
    expect(classifyPosition({ string: '$x', type: null }, PREFIXES))
      .toEqual({ kind: 'none' })
  })

  it('returns none for a string literal token', () => {
    expect(classifyPosition({ string: '"hello', type: 'string' }, PREFIXES))
      .toEqual({ kind: 'none' })
  })

  it('returns none for an empty token', () => {
    expect(classifyPosition({ string: '', type: null }, PREFIXES))
      .toEqual({ kind: 'none' })
  })

  it('returns none for keywords without prefix:', () => {
    expect(classifyPosition({ string: 'SELECT', type: 'keyword' }, PREFIXES))
      .toEqual({ kind: 'none' })
  })
})
