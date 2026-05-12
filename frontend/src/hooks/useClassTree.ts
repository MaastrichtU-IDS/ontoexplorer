import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

export type EntityType = 'class' | 'property' | 'object_property' | 'data_property' | 'annotation_property'

export function useClassTreeNodes(
  ontologyId: string | null,
  versionId: string | null,
  parent: string | null,
  entityType: EntityType = 'class',
) {
  return useQuery({
    queryKey: ['class-tree', ontologyId, versionId, parent ?? 'root', entityType],
    queryFn: () => api.ontologies.terms(ontologyId!, versionId!, parent, entityType),
    enabled: !!ontologyId && !!versionId,
    staleTime: 60_000,
  })
}
