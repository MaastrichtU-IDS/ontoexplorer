import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, OntologyDiff } from '../lib/api'

/**
 * Returns the refetch interval (ms) for a diff query, or false to stop polling.
 *  - 3 s while the diff itself is still computing (status='pending')
 *  - 30 s while the diff is ready but reasoning isn't ready for one or both
 *    sides; the backend re-queues compute_diff on reasoning completion, so
 *    polling lets the UI pick up the refreshed payload promptly.
 *  - false otherwise (everything fresh).
 */
function diffRefetchInterval(data: OntologyDiff | undefined): number | false {
  if (!data) return false
  if (data.status === 'pending') return 3000
  const inferred = data.summary?.inferred_status
  if (inferred && (inferred.from_version !== 'ready' || inferred.to_version !== 'ready')) {
    return 30_000
  }
  return false
}

export function useConsecutiveDiff(
  ontologyId: string | null,
  versionId: string | null,
) {
  return useQuery({
    queryKey: ['diff', ontologyId, versionId],
    queryFn: () => api.ontologies.diff(ontologyId!, versionId!),
    enabled: !!ontologyId && !!versionId,
    refetchInterval: (query) => diffRefetchInterval(query.state.data),
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
    refetchInterval: (query) => diffRefetchInterval(query.state.data),
    staleTime: 60_000,
  })
}

export function useGenerateNarrative(ontologyId: string, versionId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.ontologies.generateNarrative(ontologyId, versionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['diff', ontologyId] })
    },
  })
}
