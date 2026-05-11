import { useQuery } from '@tanstack/react-query'
import { api, UserProfile } from '../lib/api'

export type { UserProfile }

export function useAuth() {
  const { data, isLoading, error } = useQuery<UserProfile>({
    queryKey: ['auth', 'me'],
    queryFn: api.auth.me,
    retry: false,
    staleTime: 5 * 60 * 1000,
  })

  return {
    user: data ?? null,
    isAuthenticated: !!data && !error,
    isLoading,
  }
}
