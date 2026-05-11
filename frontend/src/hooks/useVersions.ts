import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

export function useVersions(oid: string | undefined) {
  return useQuery({
    queryKey: ['versions', oid],
    queryFn: () => api.ontologies.versions(oid!),
    enabled: !!oid,
    staleTime: 30_000,
  })
}
