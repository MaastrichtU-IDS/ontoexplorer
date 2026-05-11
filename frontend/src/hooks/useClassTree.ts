import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

export function useClassTreeNodes(
  ontologyId: string | null,
  versionId: string | null,
  parent: string | null,
) {
  return useQuery({
    queryKey: ['class-tree', ontologyId, versionId, parent ?? 'root'],
    queryFn: () => api.ontologies.terms(ontologyId!, versionId!, parent),
    enabled: !!ontologyId && !!versionId,
    staleTime: 60_000,
  })
}
