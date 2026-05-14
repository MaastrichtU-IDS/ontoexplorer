import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, OntologyProfileData, ProfilePatch, ProfileCandidates } from '../lib/api'

export function useOntologyProfile(ontologyId: string | undefined, versionId: string | undefined) {
  return useQuery<OntologyProfileData>({
    queryKey: ['profile', ontologyId, versionId],
    queryFn: () => api.ontologies.profile.get(ontologyId!, versionId!),
    enabled: !!ontologyId && !!versionId,
    retry: false,
  })
}

export function useProfileCandidates(ontologyId: string | undefined, versionId: string | undefined) {
  return useQuery<ProfileCandidates>({
    queryKey: ['profile-candidates', ontologyId, versionId],
    queryFn: () => api.ontologies.profile.candidates(ontologyId!, versionId!),
    enabled: !!ontologyId && !!versionId,
    retry: false,
  })
}

export function usePatchProfile(ontologyId: string, versionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ProfilePatch) => api.ontologies.profile.patch(ontologyId, versionId, body),
    onSuccess: (data) => {
      qc.setQueryData(['profile', ontologyId, versionId], data)
    },
  })
}

export function useDetectProfile(ontologyId: string, versionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.ontologies.profile.detect(ontologyId, versionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['profile', ontologyId, versionId] })
    },
  })
}
