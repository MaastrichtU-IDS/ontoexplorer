import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

export function useOntologies() {
  const { data, isLoading } = useQuery({
    queryKey: ['ontologies'],
    // Fetch the full catalogue (API caps at 500), not the default first page of
    // 50 — OntologyPage resolves the clicked ontology client-side by slug over
    // this list, so a short page made every ontology past the 50th unreachable
    // ("Ontology <x> not found") once the corpus grew beyond one page.
    queryFn: () => api.ontologies.list(0, 500),
    staleTime: 30_000,
  })
  return { ontologies: data?.ontologies ?? [], isLoading }
}
