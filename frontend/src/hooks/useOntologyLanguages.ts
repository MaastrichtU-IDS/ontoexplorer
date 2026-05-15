import { useQuery } from '@tanstack/react-query'
import { api, OntologyLanguage } from '../lib/api'

export function useOntologyLanguages(
  ontologyId: string | undefined,
  versionId: string | undefined,
): OntologyLanguage[] {
  const { data } = useQuery({
    queryKey: ['languages', ontologyId, versionId],
    queryFn: () => api.ontologies.languages(ontologyId!, versionId!),
    enabled: Boolean(ontologyId && versionId),
    staleTime: 5 * 60 * 1000,
  })
  return data ?? []
}
