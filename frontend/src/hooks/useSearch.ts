import { useQuery } from '@tanstack/react-query'
import { api, AutocompleteResponse } from '../lib/api'

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
  return useQuery<AutocompleteResponse>({
    queryKey: ['autocomplete', ontologyId, versionId, query, cursor],
    queryFn: () =>
      versionId
        ? api.ontologies.autocomplete(ontologyId!, versionId, query, cursor)
        : api.ontologies.autocompleteLatest(ontologyId!, query, cursor),
    enabled: enabled && !!ontologyId && query.length >= 1,
    staleTime: 5_000,
  })
}

export function useGlobalSearch(query: string, semantic = false) {
  return useQuery({
    queryKey: ['global-search', query, semantic],
    queryFn: () => api.globalSearch.search(query, 20, semantic),
    enabled: query.length >= 2,
    staleTime: 10_000,
  })
}
