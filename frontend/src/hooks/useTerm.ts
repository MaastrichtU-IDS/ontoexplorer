import { useQuery } from '@tanstack/react-query'
import { api, parseTerm, ParsedTerm } from '../lib/api'

export function useTerm(ontologyId: string | null, versionId: string | null, termIri: string | null) {
  return useQuery<ParsedTerm>({
    queryKey: ['term', ontologyId, versionId, termIri],
    queryFn: async () => {
      const raw = await api.ontologies.termDetail(ontologyId!, versionId!, termIri!)
      return parseTerm(raw)
    },
    enabled: !!ontologyId && !!versionId && !!termIri,
    staleTime: 60_000,
  })
}
