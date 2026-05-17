import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

const OWL_THING = 'http://www.w3.org/2002/07/owl#Thing'

export function useInferredTreeNodes(
  ontologyId: string | null,
  versionId: string | null,
  parent: string | null,  // null = root (owl:Thing)
  lang?: string | null,
  hideObsolete = true,
) {
  const cls = parent ?? OWL_THING
  return useQuery({
    queryKey: ['inferred-tree', ontologyId, versionId, cls, lang ?? '', hideObsolete],
    queryFn: () => api.ontologies.inferredChildren(ontologyId!, versionId!, cls, lang, hideObsolete),
    enabled: !!ontologyId && !!versionId,
    staleTime: 60_000,
  })
}
