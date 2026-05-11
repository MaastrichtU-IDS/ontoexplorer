import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

export function useOntologies() {
  const { data, isLoading } = useQuery({
    queryKey: ['ontologies'],
    queryFn: () => api.ontologies.list(),
    staleTime: 30_000,
  })
  return { ontologies: data?.ontologies ?? [], isLoading }
}
