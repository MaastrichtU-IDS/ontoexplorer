import { useQuery } from '@tanstack/react-query'
import { useState, useEffect } from 'react'
import { api } from '../lib/api'

function useDebounce<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return debounced
}

export function useOntologySearch(query: string) {
  const q = useDebounce(query.trim(), 250)
  return useQuery({
    queryKey: ['ontologies', 'search', q],
    queryFn: () => api.ontologies.list(0, 20, q || undefined),
    staleTime: 30_000,
  })
}
