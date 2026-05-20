import type { Ontology } from '../../lib/api'
import { extractBaseIri } from './prefixUtils'

/**
 * Find the ontology whose base IRI is a prefix of `iri`. If multiple match,
 * the one with the longest base IRI wins (more specific match). Ontologies
 * without a `latest_version` are ignored.
 */
export function findOwningOntology(iri: string, ontologies: Ontology[]): Ontology | null {
  let best: Ontology | null = null
  let bestLen = 0
  for (const o of ontologies) {
    if (!o.latest_version) continue
    const base = extractBaseIri(o.iri)
    if (iri.startsWith(base) && base.length > bestLen) {
      best = o
      bestLen = base.length
    }
  }
  return best
}

/**
 * Build the OntoExplorer term-page URL for an IRI inside an ontology.
 */
export function termPageUrl(shortname: string, iri: string): string {
  return `/ontologies/${shortname}?term=${encodeURIComponent(iri)}`
}
