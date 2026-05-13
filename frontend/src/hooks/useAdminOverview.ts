import { useQuery } from '@tanstack/react-query'
import { api, AdminOverview } from '../lib/api'

export function useAdminOverview() {
  return useQuery<AdminOverview>({
    queryKey: ['admin', 'overview'],
    queryFn: api.admin.overview,
    refetchInterval: 10_000,
    staleTime: 0,
  })
}
