/**
 * OAuth redirect and in-memory token management.
 * Access token is stored in memory (not localStorage) to avoid XSS exposure.
 * Refresh token is stored in an httpOnly cookie (set by the server).
 */

let _accessToken: string | null = null

export function getAccessToken(): string | null {
  // On first load, try to pick up the token from the server-set cookie
  // (the cookie is readable by JS — only the refresh token is httpOnly)
  if (!_accessToken) {
    const match = document.cookie.match(/(?:^|;\s*)access_token=([^;]+)/)
    if (match) {
      _accessToken = decodeURIComponent(match[1])
      // Clear the readable cookie; we hold the token in memory from here
      document.cookie = 'access_token=; Max-Age=0; path=/'
    }
  }
  return _accessToken
}

export function setAccessToken(token: string): void {
  _accessToken = token
}

export function clearAccessToken(): void {
  _accessToken = null
}

export function loginWithProvider(provider: 'orcid' | 'github' | 'google'): void {
  window.location.href = `/auth/${provider}/login`
}

/**
 * Link an additional provider to the CURRENT account. Unlike login, this needs
 * the auth header, so we fetch the authorize URL via the API client (which sets
 * the signed oauth_link cookie) and then navigate to it. The /callback attaches
 * the provider and bounces back to /profile.
 */
export async function linkProvider(provider: 'orcid' | 'github' | 'google'): Promise<void> {
  const { api } = await import('./api')
  const { authorize_url } = await api.auth.linkStart(provider)
  window.location.href = authorize_url
}

export async function refreshAccessToken(): Promise<string | null> {
  // Refresh token is in an httpOnly cookie — the browser sends it automatically
  try {
    const resp = await fetch('/auth/refresh', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: '' }), // server reads from cookie
    })
    if (!resp.ok) {
      clearAccessToken()
      return null
    }
    const data = await resp.json()
    setAccessToken(data.access_token)
    return data.access_token
  } catch {
    return null
  }
}

export async function logout(): Promise<void> {
  await fetch('/auth/logout', { method: 'POST', credentials: 'include' })
  clearAccessToken()
  window.location.href = '/'
}
