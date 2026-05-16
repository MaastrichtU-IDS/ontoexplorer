import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, OntologyDiff } from '../lib/api'

function isPending(data: OntologyDiff | undefined): boolean {
  return data?.status === 'pending'
}

export function useConsecutiveDiff(
  ontologyId: string | null,
  versionId: string | null,
) {
  return useQuery({
    queryKey: ['diff', ontologyId, versionId],
    queryFn: () => api.ontologies.diff(ontologyId!, versionId!),
    enabled: !!ontologyId && !!versionId,
    refetchInterval: (query) => isPending(query.state.data) ? 3000 : false,
    staleTime: 60_000,
  })
}

export function useArbitraryDiff(
  ontologyId: string | null,
  fromVid: string | null,
  toVid: string | null,
) {
  return useQuery({
    queryKey: ['diff', ontologyId, fromVid, toVid],
    enabled: !!ontologyId && !!fromVid && !!toVid && fromVid !== toVid,
    queryFn: () => api.ontologies.diffArbitrary(ontologyId!, fromVid!, toVid!),
    refetchInterval: (query) => isPending(query.state.data) ? 3000 : false,
    staleTime: 60_000,
  })
}

export function useGenerateNarrative(ontologyId: string, versionId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.ontologies.generateNarrative(ontologyId, versionId),
    onSuccess: () => {
      // Invalidate the consecutive diff so the narrative appears
      queryClient.invalidateQueries({ queryKey: ['diff', ontologyId, versionId] })
    },
  })
}
