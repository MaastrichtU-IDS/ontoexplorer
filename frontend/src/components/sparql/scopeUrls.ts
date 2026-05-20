import type { Ontology } from '../../lib/api'

export type ReasoningMode = 'asserted' | 'inferred' | 'both'

export function assertedGraphIri(ontologyId: string, versionId: string): string {
  return `urn:ontology:${ontologyId}:${versionId}`
}

export function inferredGraphIri(ontologyId: string, versionId: string): string {
  return `urn:ontology:${ontologyId}:${versionId}:inferred`
}

export function selectedGraphIris(
  selected: Set<string>,
  mode: ReasoningMode,
  ontologies: Ontology[],
): string[] {
  const out: string[] = []
  for (const o of ontologies) {
    if (!selected.has(o.id)) continue
    if (!o.latest_version) continue
    const vid = o.latest_version.id
    if (mode === 'asserted' || mode === 'both') {
      out.push(assertedGraphIri(o.id, vid))
    }
    if (mode === 'inferred' || mode === 'both') {
      out.push(inferredGraphIri(o.id, vid))
    }
  }
  return out
}

// Assumes baseUrl has no existing query string (it's a fixed app-internal
// SPARQL endpoint path). Don't pass URLs that may already contain a `?`.
export function buildScopedEndpoint(baseUrl: string, graphIris: string[]): string {
  if (graphIris.length === 0) return baseUrl
  const params: string[] = []
  for (const uri of graphIris) {
    const enc = encodeURIComponent(uri)
    params.push(`default-graph-uri=${enc}`)
    params.push(`named-graph-uri=${enc}`)
  }
  return `${baseUrl}?${params.join('&')}`
}

export function formatScopeAsFromClauses(graphIris: string[]): string {
  return graphIris.map(uri => `FROM <${uri}>\nFROM NAMED <${uri}>\n`).join('')
}
