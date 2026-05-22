import type { Ontology, OntologyVersion } from '../../lib/api'

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

/**
 * Remove any FROM / FROM NAMED lines whose IRI matches our managed
 * `urn:ontology:` scheme. Hand-written FROM clauses with other IRI patterns
 * are left alone. Used to keep the editor's scope-managed FROM list in sync
 * with the ScopeToolbar's chip selection.
 */
const MANAGED_FROM_LINE = /^[ \t]*FROM(?:[ \t]+NAMED)?[ \t]+<urn:ontology:[^>]+>[ \t]*\r?\n?/gm

export function stripManagedFromClauses(text: string): string {
  return text.replace(MANAGED_FROM_LINE, '')
}

/**
 * Build a scoped /sparql/content endpoint URL for a single (version, mode)
 * tuple. Convenience over `buildScopedEndpoint` for callers that already have
 * the OntologyVersion in hand (e.g. the diff-mode toolbar).
 */
export function endpointForVersion(version: OntologyVersion, mode: ReasoningMode): string {
  const iris: string[] = []
  if (mode === 'asserted' || mode === 'both') {
    iris.push(assertedGraphIri(version.ontology_id, version.id))
  }
  if (mode === 'inferred' || mode === 'both') {
    iris.push(inferredGraphIri(version.ontology_id, version.id))
  }
  return buildScopedEndpoint('/api/v1/sparql/content', iris)
}
