import { useQuery } from '@tanstack/react-query'
import { useState, useEffect } from 'react'
import { api, ProfileName, LanguageTier } from '../lib/api'

function useDebounce<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return debounced
}

export function useOntologySearch(
  query: string,
  group?: string,
  profile?: ProfileName,
  reuses?: string,
  language?: LanguageTier,
) {
  const q = useDebounce(query.trim(), 250)
  return useQuery({
    queryKey: ['ontologies', 'search', q, group ?? '', profile ?? '', reuses ?? '', language ?? ''],
    // Fetch the whole (group/profile/language-scoped) set, not a 200-row page:
    // the list view has no pagination and applies the Lang filter client-side, so
    // a low cap silently truncated large groups (e.g. LOV has 750+ ontologies).
    // view='list' → lean per-row projection (~half the bytes); the table only
    // needs name/chips/counts/modified-date, and OntologyPicker only id + iri.
    queryFn: () => api.ontologies.list(0, 2000, q || undefined, group || undefined, profile, reuses, false, language, 'list'),
    staleTime: 30_000,
  })
}
