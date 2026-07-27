import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { api } from '../lib/api'

export function useEntities(params: { type: string; limit: number; cursor?: string | null; lang?: string | null; q?: string }) {
  return useQuery({
    queryKey: ['entities', params.type, params.limit, params.cursor ?? '', params.lang ?? '', params.q ?? ''],
    queryFn: () => api.entities.list(params),
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  })
}
