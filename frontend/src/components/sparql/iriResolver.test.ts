import { describe, it, expect } from 'vitest'
import { findOwningOntology, termPageUrl } from './iriResolver'
import type { Ontology } from '../../lib/api'

const PIZZA: Ontology = {
  id: 'O1', iri: 'https://w3id.org/ontostart/pizza/', shortname: 'pizza',
  title: 'Pizza', created_at: '2024-01-01',
  latest_version: { id: 'V1', ontology_id: 'O1', status: 'ready' } as any,
} as any

const OBO: Ontology = {
  id: 'O2', iri: 'http://purl.obolibrary.org/obo/', shortname: 'obo',
  title: 'OBO', created_at: '2024-01-01',
  latest_version: { id: 'V2', ontology_id: 'O2', status: 'ready' } as any,
} as any

const CHEBI: Ontology = {
  id: 'O3', iri: 'http://purl.obolibrary.org/obo/chebi/', shortname: 'chebi',
  title: 'ChEBI', created_at: '2024-01-01',
  latest_version: { id: 'V3', ontology_id: 'O3', status: 'ready' } as any,
} as any

describe('findOwningOntology', () => {
  it('returns null when no ontology matches', () => {
    expect(findOwningOntology('http://example.org/Foo', [PIZZA])).toBeNull()
  })

  it('returns the ontology when iri starts with its base', () => {
    expect(findOwningOntology('https://w3id.org/ontostart/pizza/Margherita', [PIZZA]))
      .toBe(PIZZA)
  })

  it('picks the longest-prefix match when multiple ontologies match', () => {
    // CHEBI's base is a longer prefix of obo:chebi/12345 than OBO's
    const iri = 'http://purl.obolibrary.org/obo/chebi/12345'
    expect(findOwningOntology(iri, [OBO, CHEBI])).toBe(CHEBI)
  })

  it('normalises ontology IRIs without trailing terminator', () => {
    // Ontology IRI lacks a trailing slash; the iri lookup still works
    const o: Ontology = { ...PIZZA, iri: 'https://w3id.org/ontostart/pizza' } as any
    expect(findOwningOntology('https://w3id.org/ontostart/pizza/Foo', [o])).toBe(o)
  })

  it('returns null when ontology has no latest_version', () => {
    const stale: Ontology = { ...PIZZA, latest_version: null } as any
    expect(findOwningOntology('https://w3id.org/ontostart/pizza/Foo', [stale])).toBeNull()
  })
})

describe('termPageUrl', () => {
  it('builds /ontologies/<shortname>?term=<encoded-iri>', () => {
    expect(termPageUrl('pizza', 'https://w3id.org/ontostart/pizza/Margherita'))
      .toBe('/ontologies/pizza?term=https%3A%2F%2Fw3id.org%2Fontostart%2Fpizza%2FMargherita')
  })

  it('encodes hash fragments in the IRI', () => {
    expect(termPageUrl('owl', 'http://www.w3.org/2002/07/owl#Class'))
      .toBe('/ontologies/owl?term=http%3A%2F%2Fwww.w3.org%2F2002%2F07%2Fowl%23Class')
  })
})
