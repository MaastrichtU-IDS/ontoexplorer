import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, OntologyComparison, ComparisonPending } from '../lib/api'

function isPending(data: OntologyComparison | ComparisonPending | undefined): boolean {
  return data?.status === 'pending'
}

/**
 * Polls /compare every 2s until the result is ready or failed.
 * `enabled` controls when polling starts (both version IDs present + distinct).
 *
 * Caller flow: call api.compare.compute(...) once via useTriggerComparison,
 * then read the result via this hook. The hook is keyed off the version pair.
 */
export function useArbitraryComparison(
  fromVid: string | null,
  toVid: string | null,
) {
  const enabled = !!fromVid && !!toVid && fromVid !== toVid
  return useQuery({
    queryKey: ['compare', fromVid, toVid],
    enabled,
    queryFn: async () => {
      try {
        return await api.compare.get(fromVid!, toVid!)
      } catch (err) {
        // 404 = comparison not yet requested. Return a synthetic pending
        // status so the polling loop can wait until POST /compute lands a row.
        if (err instanceof Error && /404/.test(err.message)) {
          return { status: 'pending' } as ComparisonPending
        }
        throw err
      }
    },
    refetchInterval: (query) => isPending(query.state.data) ? 2000 : false,
    staleTime: 60_000,
  })
}

/**
 * One-shot POST /compare/compute. Use with the version pair to trigger the
 * Celery task. Successful POST returns immediately with a "pending" status
 * even if the worker hasn't finished yet — useArbitraryComparison handles
 * the polling.
 */
export function useTriggerComparison() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ fromVid, toVid }: { fromVid: string; toVid: string }) =>
      api.compare.compute(fromVid, toVid),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ['compare', vars.fromVid, vars.toVid] })
    },
  })
}
