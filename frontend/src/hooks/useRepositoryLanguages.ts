import { useQuery } from '@tanstack/react-query'
import { api, OntologyLanguage } from '../lib/api'

export function useRepositoryLanguages(): OntologyLanguage[] {
  const { data } = useQuery({
    queryKey: ['repository-languages'],
    queryFn: () => api.languages.list(),
    staleTime: 5 * 60_000,
  })
  return data ?? []
}
