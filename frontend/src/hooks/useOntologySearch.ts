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
    queryFn: () => api.ontologies.list(0, 200, q || undefined, group || undefined, profile, reuses, false, language),
    staleTime: 30_000,
  })
}
