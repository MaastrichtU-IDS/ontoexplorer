/**
 * Typed API client with automatic JWT refresh on 401.
 */

import { getAccessToken, refreshAccessToken } from './auth'

const BASE = '/api/v1'

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getAccessToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  }
  if (token) headers['Authorization'] = `Bearer ${token}`

  let resp = await fetch(`${BASE}${path}`, { ...options, headers })

  if (resp.status === 401) {
    const newToken = await refreshAccessToken()
    if (newToken) {
      headers['Authorization'] = `Bearer ${newToken}`
      resp = await fetch(`${BASE}${path}`, { ...options, headers })
    }
  }

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw new Error(err.detail ?? 'Request failed')
  }

  if (resp.status === 204) return undefined as T
  return resp.json()
}

// ── Types ──────────────────────────────────────────────────────────────────────

export interface UserProfile {
  id: string
  email: string | null
  display_name: string | null
  created_at: string
}

export interface Ontology {
  id: string
  iri: string
  created_at: string
}

export interface OntologyVersion {
  id: string
  ontology_id: string
  version_iri: string | null
  format: string
  status: string
  sha256: string
  download_url: string
  created_at: string
}

export interface Job {
  id: string
  version_id: string
  type: string
  status: string
  started_at: string | null
  finished_at: string | null
  error: string | null
  created_at: string
}

export interface ApiKey {
  id: string
  name: string
  scopes: string[]
  created_at: string
  last_used_at: string | null
  key?: string  // only present on creation
}

export interface Webhook {
  id: string
  url: string
  events: string[]
  active: boolean
  created_at: string
  deliveries?: WebhookDelivery[]
}

export interface WebhookDelivery {
  id: string
  event: string
  status: string
  attempts: number
  http_status: number | null
  last_attempt_at: string | null
}

// ── API methods ────────────────────────────────────────────────────────────────

export const api = {
  auth: {
    me: () => request<UserProfile>('/../../auth/me'),
  },

  ontologies: {
    list: (offset = 0, limit = 50) =>
      request<{ ontologies: Ontology[]; offset: number; limit: number }>(
        `/ontologies?offset=${offset}&limit=${limit}`
      ),
    get: (id: string) => request<Ontology>(`/ontologies/${id}`),
    versions: (id: string) =>
      request<{ versions: OntologyVersion[] }>(`/ontologies/${id}/versions`),
    submitByIri: (iri: string) =>
      request<{ task_id: string; status: string }>('/ontologies', {
        method: 'POST',
        body: JSON.stringify({ iri }),
      }),
    submitByUrl: (url: string) =>
      request<{ task_id: string; status: string }>('/ontologies', {
        method: 'POST',
        body: JSON.stringify({ url }),
      }),
  },

  jobs: {
    list: (params?: { type?: string; status?: string; limit?: number }) => {
      const q = new URLSearchParams()
      if (params?.type) q.set('type', params.type)
      if (params?.status) q.set('status', params.status)
      if (params?.limit) q.set('limit', String(params.limit))
      return request<{ jobs: Job[] }>(`/jobs?${q}`)
    },
    get: (id: string) => request<Job>(`/jobs/${id}`),
  },

  apiKeys: {
    list: () => request<{ api_keys: ApiKey[] }>('/api-keys'),
    create: (name: string, scopes: string[]) =>
      request<ApiKey>('/api-keys', {
        method: 'POST',
        body: JSON.stringify({ name, scopes }),
      }),
    revoke: (id: string) => request<void>(`/api-keys/${id}`, { method: 'DELETE' }),
  },

  webhooks: {
    list: () => request<{ webhooks: Webhook[] }>('/webhooks'),
    get: (id: string) => request<Webhook>(`/webhooks/${id}`),
    deliveries: (id: string) => request<{ deliveries: WebhookDelivery[] }>(`/webhooks/${id}/deliveries`),
    create: (url: string, events: string[], secret?: string) =>
      request<Webhook>('/webhooks', {
        method: 'POST',
        body: JSON.stringify({ url, events, secret }),
      }),
    delete: (id: string) => request<void>(`/webhooks/${id}`, { method: 'DELETE' }),
    test: (id: string) => request<{ delivery_id: string; status: string }>(`/webhooks/${id}/test`, { method: 'POST' }),
  },

  stats: {
    get: () => request<{
      total_ontologies: number
      total_versions: number
      storage_bytes: number
      total_queries: number
      uploads_per_month: Array<{ month: string; count: number }>
      queries_per_month: Array<{ month: string; count: number }>
      job_durations: Array<{ month: string; avg_seconds: number }>
    }>('/stats'),
  },
}
