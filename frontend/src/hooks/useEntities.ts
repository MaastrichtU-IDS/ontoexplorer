import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { api } from '../lib/api'

export function useEntities(params: { type: string; limit: number; cursor?: string | null; q?: string; collapse?: boolean }) {
  return useQuery({
    queryKey: ['entities', params.type, params.limit, params.cursor ?? '', params.q ?? '', params.collapse ? 1 : 0],
    queryFn: () => api.entities.list(params),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  })
}
