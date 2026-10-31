import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

export function useFacets(type: string) {
  const { data, isLoading } = useQuery({
    queryKey: ['entity-facets', type],
    queryFn: () => api.entities.facets(type),
    staleTime: 30_000,
  })
  return { facets: data ?? [], isLoading }
}
