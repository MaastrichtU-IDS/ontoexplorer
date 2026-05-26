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

export function useGlobalAutocomplete(
  query: string,
  cursor: number,
  enabled: boolean,
  ontologyIds: string[] = [],
) {
  return useQuery<AutocompleteResponse>({
    queryKey: ['global-autocomplete', query, cursor, ontologyIds],
    queryFn: () => api.globalSearch.autocomplete(query, cursor, ontologyIds),
    enabled: enabled && query.length >= 1,
    staleTime: 5_000,
  })
}

export function useGlobalSearch(query: string, semantic = false, types: string[] = []) {
  const typesKey = [...types].sort().join(',')
  return useQuery({
    queryKey: ['global-search', query, semantic, typesKey],
    queryFn: () => api.globalSearch.search(query, 20, semantic, types),
    enabled: query.length >= 2,
    staleTime: 10_000,
  })
}
