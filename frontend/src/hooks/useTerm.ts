import { useQuery } from '@tanstack/react-query'
import { api, parseTerm, ParsedTerm, InferredExprEntry, InheritedSchemaProperty, ClassUsageEntry } from '../lib/api'

export function useTerm(
  ontologyId: string | null,
  versionId: string | null,
  termIri: string | null,
  lang?: string | null,
) {
  return useQuery<ParsedTerm>({
    queryKey: ['term', ontologyId, versionId, termIri, lang],
    queryFn: async () => {
      const raw = await api.ontologies.termDetail(ontologyId!, versionId!, termIri!, lang ?? undefined)
      return parseTerm(raw)
    },
    enabled: !!ontologyId && !!versionId && !!termIri,
    staleTime: 60_000,
  })
}

export interface TermExpandedSections {
  inferredSuperclassExpressions: InferredExprEntry[]
  inferredDisjointWith: InferredExprEntry[]
  inheritedSchemaProperties: InheritedSchemaProperty[]
  /** Moved off the main term response: finding the restrictions that reference
   *  a class costs ~4 s on a large ontology regardless of the class. */
  classUsage: ClassUsageEntry[]
  classUsageHasMore: boolean
}

/**
 * Lazy fetch of the three expensive ancestor-walking sections that the main
 * /terms/{iri} endpoint now defers. The frontend renders the main panel
 * immediately and these sections fill in once this query resolves.
 */
export function useTermExpanded(
  ontologyId: string | null,
  versionId: string | null,
  termIri: string | null,
  lang?: string | null,
) {
  return useQuery<TermExpandedSections>({
    queryKey: ['term-expanded', ontologyId, versionId, termIri, lang],
    queryFn: async () => {
      const raw = await api.ontologies.termExpanded(ontologyId!, versionId!, termIri!, lang ?? undefined)
      return {
        inferredSuperclassExpressions: raw.inferred_superclass_expressions ?? [],
        inferredDisjointWith:          raw.inferred_disjoint_with         ?? [],
        inheritedSchemaProperties:     raw.inherited_schema_properties    ?? [],
        classUsage:                    raw.class_usage                    ?? [],
        classUsageHasMore:             raw.class_usage_has_more           ?? false,
      }
    },
    enabled: !!ontologyId && !!versionId && !!termIri,
    staleTime: 60_000,
  })
}
