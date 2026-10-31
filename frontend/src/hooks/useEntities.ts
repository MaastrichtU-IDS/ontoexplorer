import { useQuery } from '@tanstack/react-query'
import { api, type EntityListParams } from '../lib/api'

export function useEntities(params: EntityListParams) {
  const { data, isLoading, isFetching, error } = useQuery({
    queryKey: ['entities', params],
    queryFn: () => api.entities.list(params),
    staleTime: 30_000,
  })
  return { data, entities: data?.entities ?? [], isLoading, isFetching, error }
}
