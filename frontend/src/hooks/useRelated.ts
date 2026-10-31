import { useQuery } from '@tanstack/react-query'
import { api, type EntityRelatedParams } from '../lib/api'

export function useRelated(params: EntityRelatedParams, enabled = true) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['entities-related', params],
    queryFn: () => api.entities.related(params),
    enabled: enabled && !!params.q,
    staleTime: 30_000,
  })
  return {
    entities: data?.entities ?? [],
    unavailable: data?.unavailable ?? false,
    isLoading,
    error,
  }
}
