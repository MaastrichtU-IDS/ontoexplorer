import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, OntologyMetaProfile, MetaProfilePatch } from '../lib/api'

export function useOntologyMeta(
  ontologyId: string | undefined,
  versionId: string | undefined,
) {
  return useQuery<OntologyMetaProfile>({
    queryKey: ['meta-profile', ontologyId, versionId],
    queryFn: () => api.ontologies.meta.get(ontologyId!, versionId!),
    enabled: !!ontologyId && !!versionId,
    retry: false,
  })
}

export function useMetaCandidates(
  ontologyId: string | undefined,
  versionId: string | undefined,
) {
  return useQuery<{ version_id: string; [key: string]: unknown }>({
    queryKey: ['meta-candidates', ontologyId, versionId],
    queryFn: () => api.ontologies.meta.candidates(ontologyId!, versionId!),
    enabled: !!ontologyId && !!versionId,
    retry: false,
  })
}

export function usePatchMeta(ontologyId: string, versionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: MetaProfilePatch) =>
      api.ontologies.meta.patch(ontologyId, versionId, body),
    onSuccess: (data) => {
      qc.setQueryData(['meta-profile', ontologyId, versionId], data)
    },
  })
}

export function useDetectMeta(ontologyId: string, versionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.ontologies.meta.detect(ontologyId, versionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['meta-profile', ontologyId, versionId] })
    },
  })
}
