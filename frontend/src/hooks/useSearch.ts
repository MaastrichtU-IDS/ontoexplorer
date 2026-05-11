import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

export function useSearch(ontologyId: string | null, versionId: string | null, query: string) {
  return useQuery({
    queryKey: ['search', ontologyId, versionId, query],
    queryFn: () => api.ontologies.search(ontologyId!, versionId!, query),
    enabled: !!ontologyId && !!versionId && query.length >= 2,
    staleTime: 10_000,
    retry: false,
  })
}

export function useAutocomplete(
  ontologyId: string | null,
  versionId: string | null,
  query: string,
  cursor: number,
  enabled: boolean,
) {
  return useQuery({
    queryKey: ['autocomplete', ontologyId, versionId, query, cursor],
    queryFn: () => api.ontologies.autocomplete(ontologyId!, versionId!, query, cursor),
    enabled: enabled && !!ontologyId && !!versionId && query.length >= 1,
    staleTime: 5_000,
  })
}

export function useGlobalSearch(query: string) {
  return useQuery({
    queryKey: ['global-search', query],
    queryFn: () => api.globalSearch.search(query),
    enabled: query.length >= 2,
    staleTime: 10_000,
  })
}
