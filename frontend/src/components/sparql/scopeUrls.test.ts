import { describe, it, expect } from 'vitest'
import { assertedGraphIri, inferredGraphIri, selectedGraphIris, buildScopedEndpoint, formatScopeAsFromClauses, endpointForVersion } from './scopeUrls'
import type { Ontology, OntologyVersion } from '../../lib/api'

const ONTS: Ontology[] = [
  {
    id: 'O1', iri: 'http://example.org/o1', shortname: 'o1', title: null,
    created_at: '2024-01-01', latest_version: {
      id: 'V1', ontology_id: 'O1', status: 'ready', format: 'owl',
      version_iri: null, sha256: '',
    } as any,
  } as any,
  {
    id: 'O2', iri: 'http://example.org/o2', shortname: 'o2', title: null,
    created_at: '2024-01-01', latest_version: {
      id: 'V2', ontology_id: 'O2', status: 'ready', format: 'owl',
      version_iri: null, sha256: '',
    } as any,
  } as any,
]

describe('assertedGraphIri', () => {
  it('builds urn:ontology:O:V', () => {
    expect(assertedGraphIri('O1', 'V1')).toBe('urn:ontology:O1:V1')
  })
})

describe('inferredGraphIri', () => {
  it('builds urn:ontology:O:V:inferred', () => {
    expect(inferredGraphIri('O1', 'V1')).toBe('urn:ontology:O1:V1:inferred')
  })
})

describe('selectedGraphIris', () => {
  it('returns [] for empty selection regardless of mode', () => {
    expect(selectedGraphIris(new Set(), 'asserted', ONTS)).toEqual([])
    expect(selectedGraphIris(new Set(), 'inferred', ONTS)).toEqual([])
    expect(selectedGraphIris(new Set(), 'both', ONTS)).toEqual([])
  })

  it('returns asserted URI for mode=asserted', () => {
    expect(selectedGraphIris(new Set(['O1']), 'asserted', ONTS))
      .toEqual(['urn:ontology:O1:V1'])
  })

  it('returns inferred + consistency-inferred URIs for mode=inferred', () => {
    // Phase-2 consistency entailments live in a separate graph that must be
    // included whenever the user asks for inferred axioms (see scopeUrls.ts).
    expect(selectedGraphIris(new Set(['O1']), 'inferred', ONTS))
      .toEqual([
        'urn:ontology:O1:V1:inferred',
        'urn:ontology:O1:V1:consistency-inferred',
      ])
  })

  it('returns asserted then inferred + consistency-inferred for mode=both', () => {
    expect(selectedGraphIris(new Set(['O1']), 'both', ONTS))
      .toEqual([
        'urn:ontology:O1:V1',
        'urn:ontology:O1:V1:inferred',
        'urn:ontology:O1:V1:consistency-inferred',
      ])
  })

  it('preserves ontology order from the input list', () => {
    expect(selectedGraphIris(new Set(['O1', 'O2']), 'asserted', ONTS))
      .toEqual(['urn:ontology:O1:V1', 'urn:ontology:O2:V2'])
  })

  it('skips selected ids not present in the ontologies list', () => {
    expect(selectedGraphIris(new Set(['O1', 'OXX']), 'asserted', ONTS))
      .toEqual(['urn:ontology:O1:V1'])
  })

  it('skips ontologies missing latest_version', () => {
    const noVer = [{ ...ONTS[0], latest_version: null } as any]
    expect(selectedGraphIris(new Set(['O1']), 'asserted', noVer)).toEqual([])
  })
})

describe('buildScopedEndpoint', () => {
  const BASE = '/api/v1/sparql/content'

  it('returns the base URL unchanged when no URIs', () => {
    expect(buildScopedEndpoint(BASE, [])).toBe(BASE)
  })

  it('appends default-graph-uri + named-graph-uri for one URI', () => {
    expect(buildScopedEndpoint(BASE, ['urn:ontology:O1:V1']))
      .toBe(`${BASE}?default-graph-uri=urn%3Aontology%3AO1%3AV1&named-graph-uri=urn%3Aontology%3AO1%3AV1`)
  })

  it('appends both params for each URI in order', () => {
    expect(buildScopedEndpoint(BASE, ['urn:a', 'urn:b']))
      .toBe(`${BASE}?default-graph-uri=urn%3Aa&named-graph-uri=urn%3Aa&default-graph-uri=urn%3Ab&named-graph-uri=urn%3Ab`)
  })
})

describe('formatScopeAsFromClauses', () => {
  it('returns empty string for empty list', () => {
    expect(formatScopeAsFromClauses([])).toBe('')
  })

  it('returns FROM + FROM NAMED for one URI', () => {
    expect(formatScopeAsFromClauses(['urn:a']))
      .toBe('FROM <urn:a>\nFROM NAMED <urn:a>\n')
  })

  it('returns four lines for two URIs in order', () => {
    expect(formatScopeAsFromClauses(['urn:a', 'urn:b']))
      .toBe('FROM <urn:a>\nFROM NAMED <urn:a>\nFROM <urn:b>\nFROM NAMED <urn:b>\n')
  })
})

describe('endpointForVersion', () => {
  const BASE = '/api/v1/sparql/content'
  const V1: OntologyVersion = {
    id: 'V1',
    ontology_id: 'O1',
    status: 'ready',
    format: 'owl',
    version_iri: null,
    sha256: '',
    triple_count: 0,
    download_url: '',
    created_at: '',
  }

  it('asserted mode emits both default and named graph params for the asserted URI', () => {
    const url = endpointForVersion(V1, 'asserted')
    const enc = encodeURIComponent('urn:ontology:O1:V1')
    expect(url).toBe(`${BASE}?default-graph-uri=${enc}&named-graph-uri=${enc}`)
  })

  it('inferred mode uses the :inferred suffix', () => {
    const url = endpointForVersion(V1, 'inferred')
    expect(url).toContain(encodeURIComponent('urn:ontology:O1:V1:inferred'))
    expect(url).not.toContain(encodeURIComponent('urn:ontology:O1:V1&'))
  })

  it('both mode emits six params (asserted + inferred + consistency-inferred)', () => {
    const url = endpointForVersion(V1, 'both')
    expect(url).toContain(encodeURIComponent('urn:ontology:O1:V1'))
    expect(url).toContain(encodeURIComponent('urn:ontology:O1:V1:inferred'))
    expect(url).toContain(encodeURIComponent('urn:ontology:O1:V1:consistency-inferred'))
    expect((url.match(/default-graph-uri=/g) ?? []).length).toBe(3)
    expect((url.match(/named-graph-uri=/g) ?? []).length).toBe(3)
  })
})
