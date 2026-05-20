import { describe, it, expect } from 'vitest'
import { extractBaseIri, hasPrefix, prependPrefix } from './prefixUtils'

describe('extractBaseIri', () => {
  it('keeps slash-terminated IRIs as-is', () => {
    expect(extractBaseIri('http://example.org/foo/')).toBe('http://example.org/foo/')
  })

  it('keeps hash-terminated IRIs as-is', () => {
    expect(extractBaseIri('http://example.org/foo#')).toBe('http://example.org/foo#')
  })

  it('appends / when neither terminator is present', () => {
    expect(extractBaseIri('http://example.org/foo')).toBe('http://example.org/foo/')
  })

  it('handles IRIs with empty path', () => {
    expect(extractBaseIri('http://example.org')).toBe('http://example.org/')
  })
})

describe('hasPrefix', () => {
  it('returns true for an exact PREFIX line', () => {
    expect(hasPrefix('PREFIX pizza: <http://x>\nSELECT * WHERE { ?s ?p ?o }', 'pizza')).toBe(true)
  })

  it('returns true ignoring case of PREFIX keyword', () => {
    expect(hasPrefix('prefix pizza: <http://x>\n', 'pizza')).toBe(true)
  })

  it('returns true with extra whitespace', () => {
    expect(hasPrefix('  PREFIX   pizza:   <http://x>\n', 'pizza')).toBe(true)
  })

  it('returns false when prefix name differs', () => {
    expect(hasPrefix('PREFIX other: <http://x>\n', 'pizza')).toBe(false)
  })

  it('returns false when no PREFIX line at all', () => {
    expect(hasPrefix('SELECT * WHERE { ?s ?p ?o }', 'pizza')).toBe(false)
  })

  it('matches in a multi-line query', () => {
    const q = 'PREFIX owl: <http://www.w3.org/2002/07/owl#>\nPREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\nSELECT * WHERE { }'
    expect(hasPrefix(q, 'rdfs')).toBe(true)
    expect(hasPrefix(q, 'owl')).toBe(true)
    expect(hasPrefix(q, 'missing')).toBe(false)
  })
})

describe('prependPrefix', () => {
  it('prepends to an empty query', () => {
    expect(prependPrefix('', 'pizza', 'http://x/')).toBe('PREFIX pizza: <http://x/>\n')
  })

  it('prepends above existing content', () => {
    expect(prependPrefix('SELECT * WHERE { ?s ?p ?o }', 'pizza', 'http://x/'))
      .toBe('PREFIX pizza: <http://x/>\nSELECT * WHERE { ?s ?p ?o }')
  })

  it('preserves existing PREFIX lines from being touched', () => {
    const before = 'PREFIX owl: <http://www.w3.org/2002/07/owl#>\nSELECT * WHERE { ?s ?p ?o }'
    expect(prependPrefix(before, 'pizza', 'http://x/'))
      .toBe('PREFIX pizza: <http://x/>\nPREFIX owl: <http://www.w3.org/2002/07/owl#>\nSELECT * WHERE { ?s ?p ?o }')
  })
})
