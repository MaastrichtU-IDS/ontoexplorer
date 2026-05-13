/**
 * Typed API client with automatic JWT refresh on 401.
 */

import { getAccessToken, refreshAccessToken, clearAccessToken } from './auth'

const BASE = '/api/v1'

// ── Error with status ─────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public body: unknown,
  ) {
    super(message)
  }
}

// ── HTTP helpers ──────────────────────────────────────────────────────────────

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getAccessToken()
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  }
  // Don't set Content-Type for FormData (let browser set boundary)
  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }
  if (token) headers['Authorization'] = `Bearer ${token}`

  let resp = await fetch(`${BASE}${path}`, { ...options, headers })

  if (resp.status === 401) {
    const newToken = await refreshAccessToken()
    if (newToken) {
      headers['Authorization'] = `Bearer ${newToken}`
      resp = await fetch(`${BASE}${path}`, { ...options, headers })
    } else {
      clearAccessToken()
      window.location.href = '/login'
      throw new ApiError('Session expired', 401, null)
    }
  }

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw new ApiError(
      (body as Record<string, string>).detail ?? 'Request failed',
      resp.status,
      body,
    )
  }

  if (resp.status === 204) return undefined as T
  return resp.json()
}

async function authFetch<T>(path: string): Promise<T> {
  const token = getAccessToken()
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  const resp = await fetch(path, { headers })
  if (!resp.ok) throw new ApiError('Not authenticated', resp.status, null)
  return resp.json()
}

// ── Types ─────────────────────────────────────────────────────────────────────

export interface UserProfile {
  id: string
  email: string | null
  display_name: string | null
  created_at: string
}

export interface Ontology {
  id: string
  iri: string
  shortname: string | null
  created_at: string
}

export interface OntologyVersion {
  id: string
  ontology_id: string
  version_iri: string | null
  format: string
  status: string
  sha256: string
  triple_count: number | null
  download_url: string
  created_at: string
}

export interface Term {
  iri: string
  label: string | null
  has_children?: boolean
  source?: string
}

export interface ClassRef {
  iri: string
  label: string
}

export interface PropertyUsage {
  class_iri: string
  class_label: string
  restriction: string
  filler_iri: string | null
  filler_label: string | null
}

export interface ClassUsageEntry {
  class_iri: string
  class_label: string
  property_iri: string | null
  property_label: string | null
  restriction: string
}

export interface InferredExprEntry {
  expr: ClassExprNode
  from_iri: string
  from_label: string
}

export interface RawTermDetail {
  iri: string
  label: string
  source?: string
  properties: Record<string, string[]>
  is_inverse_target: boolean
  superclasses: { asserted: ClassRef[]; inferred: ClassRef[] }
  subclasses: { asserted: ClassRef[]; inferred: ClassRef[] }
  superclass_expressions?: ClassExprNode[]
  inferred_superclass_expressions?: InferredExprEntry[]
  equivalent_to?: ClassExprNode[]
  disjoint_with?: ClassExprNode[]
  inferred_disjoint_with?: InferredExprEntry[]
  disjoint_union_of?: ClassExprNode[][]
  general_class_axioms?: ClassExprNode[]
  usage: PropertyUsage[]
  class_usage?: ClassUsageEntry[]
}

export interface ParsedTerm {
  iri: string
  label: string
  source?: string
  definition: string | null
  entityType: 'class' | 'property' | 'object_property' | 'data_property' | 'annotation_property' | 'individual'
  isInverseTarget: boolean
  synonyms: { exact: string[]; related: string[]; broad: string[]; narrow: string[] }
  superclasses: { asserted: ClassRef[]; inferred: ClassRef[] }
  subclasses: { asserted: ClassRef[]; inferred: ClassRef[] }
  superclassExpressions: ClassExprNode[]
  inferredSuperclassExpressions: InferredExprEntry[]
  equivalentTo: ClassExprNode[]
  disjointWith: ClassExprNode[]
  inferredDisjointWith: InferredExprEntry[]
  disjointUnionOf: ClassExprNode[][]
  generalClassAxioms: ClassExprNode[]
  domain: string[]
  range: string[]
  characteristics: string[]
  inverseOf: string[]
  usage: PropertyUsage[]
  classUsage: ClassUsageEntry[]
}

export interface OntologyMetadataEntry {
  value: string
  type: 'iri' | 'literal'
  language: string | null
  datatype: string | null
}

export interface OntologyDocumentMetadata {
  ontology_iri: string
  predicates: Record<string, OntologyMetadataEntry[]>
}

export type ClassExprNode =
  | { type: 'named'; iri: string; label: string }
  | { type: 'literal'; value: string }
  | { type: 'some' | 'only' | 'value'; property: ClassExprNode; filler: ClassExprNode }
  | { type: 'not'; operand: ClassExprNode }
  | { type: 'and' | 'or'; operands: ClassExprNode[] }
  | { type: 'min' | 'max' | 'exactly'; property: ClassExprNode; n: string; filler?: ClassExprNode }
  | { type: 'one_of'; individuals: ClassExprNode[] }
  | { type: 'unknown' }

export interface SearchResult {
  iri: string
  label: string
  short: string
  source?: string
  match_type: 'entity' | 'elk' | 'sparql'
  version_id?: string
  ontology_id?: string
}

export interface JustificationAxiom {
  sub: ClassExprNode
  rel: 'subClassOf' | 'equivalentClass' | 'disjointWith'
  sup: ClassExprNode
}

export interface JustificationResult {
  justifications: JustificationAxiom[][]
  timed_out: boolean
  reasoning_available: boolean
}

export interface AutocompleteCompletion {
  text: string
  type: string
  iri: string | null
  short: string | null
  insert: string
}

export interface AutocompleteResponse {
  completions: AutocompleteCompletion[]
  context: string
  replace_from: number
  replace_to: number
  version_id?: string
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
  key?: string
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

// ── Predicate constants ───────────────────────────────────────────────────────

const P = {
  label:       'http://www.w3.org/2000/01/rdf-schema#label',
  comment:     'http://www.w3.org/2000/01/rdf-schema#comment',
  definition:  'http://purl.obolibrary.org/obo/IAO_0000115',
  subClassOf:  'http://www.w3.org/2000/01/rdf-schema#subClassOf',
  type:        'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
  domain:      'http://www.w3.org/2000/01/rdf-schema#domain',
  range:       'http://www.w3.org/2000/01/rdf-schema#range',
  inverseOf:   'http://www.w3.org/2002/07/owl#inverseOf',
  exactSyn:    'http://www.geneontology.org/formats/oboInOwl#hasExactSynonym',
  relatedSyn:  'http://www.geneontology.org/formats/oboInOwl#hasRelatedSynonym',
  broadSyn:    'http://www.geneontology.org/formats/oboInOwl#hasBroadSynonym',
  narrowSyn:   'http://www.geneontology.org/formats/oboInOwl#hasNarrowSynonym',
  owlClass:    'http://www.w3.org/2002/07/owl#Class',
  owlObjProp:  'http://www.w3.org/2002/07/owl#ObjectProperty',
  owlDataProp: 'http://www.w3.org/2002/07/owl#DatatypeProperty',
  owlAnnProp:  'http://www.w3.org/2002/07/owl#AnnotationProperty',
  owlIndividual: 'http://www.w3.org/2002/07/owl#NamedIndividual',
}

const OWL_CHARACTERISTICS: Record<string, string> = {
  'http://www.w3.org/2002/07/owl#FunctionalProperty':        'Functional',
  'http://www.w3.org/2002/07/owl#InverseFunctionalProperty': 'InverseFunctional',
  'http://www.w3.org/2002/07/owl#TransitiveProperty':        'Transitive',
  'http://www.w3.org/2002/07/owl#SymmetricProperty':         'Symmetric',
  'http://www.w3.org/2002/07/owl#AsymmetricProperty':        'Asymmetric',
  'http://www.w3.org/2002/07/owl#ReflexiveProperty':         'Reflexive',
  'http://www.w3.org/2002/07/owl#IrreflexiveProperty':       'Irreflexive',
}

export function slugFromIri(iri: string): string {
  const last = iri.replace(/[/#]+$/, '').split(/[/#]/).pop() ?? iri
  return last.replace(/\.(owl|ttl|rdf|obo|json|xml|nt)$/i, '').toLowerCase()
}

export function parseTerm(raw: RawTermDetail): ParsedTerm {
  const p = raw.properties
  const label = p[P.label]?.[0] ?? raw.iri.split(/[#/]/).pop() ?? raw.iri
  const definition = p[P.definition]?.[0] ?? p[P.comment]?.[0] ?? null
  const types = p[P.type] ?? []
  let entityType: ParsedTerm['entityType'] = 'class'
  if (types.includes(P.owlObjProp)) {
    entityType = 'object_property'
  } else if (types.includes(P.owlDataProp)) {
    entityType = 'data_property'
  } else if (types.includes(P.owlAnnProp)) {
    entityType = 'annotation_property'
  } else if (types.includes(P.owlIndividual)) {
    entityType = 'individual'
  }
  const characteristics = types.map(t => OWL_CHARACTERISTICS[t]).filter(Boolean) as string[]
  return {
    iri: raw.iri,
    label: raw.label ?? label,
    source: raw.source ?? '',
    definition,
    entityType,
    isInverseTarget: raw.is_inverse_target ?? false,
    synonyms: {
      exact:   p[P.exactSyn]   ?? [],
      related: p[P.relatedSyn] ?? [],
      broad:   p[P.broadSyn]   ?? [],
      narrow:  p[P.narrowSyn]  ?? [],
    },
    superclasses:         raw.superclasses         ?? { asserted: [], inferred: [] },
    subclasses:           raw.subclasses            ?? { asserted: [], inferred: [] },
    superclassExpressions:          raw.superclass_expressions           ?? [],
    inferredSuperclassExpressions:  raw.inferred_superclass_expressions  ?? [],
    equivalentTo:                   raw.equivalent_to                    ?? [],
    disjointWith:          raw.disjoint_with            ?? [],
    inferredDisjointWith:  raw.inferred_disjoint_with   ?? [],
    disjointUnionOf:       raw.disjoint_union_of       ?? [],
    generalClassAxioms:    raw.general_class_axioms    ?? [],
    domain:               p[P.domain]               ?? [],
    range:           p[P.range]       ?? [],
    characteristics,
    inverseOf:       p[P.inverseOf]   ?? [],
    usage:           raw.usage        ?? [],
    classUsage:      raw.class_usage  ?? [],
  }
}

// ── API surface ───────────────────────────────────────────────────────────────

export const api = {
  auth: {
    me: () => authFetch<UserProfile>('/auth/me'),
  },

  ontologies: {
    list: (offset = 0, limit = 50, q?: string) => {
      const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
      if (q) params.set('q', q)
      return request<{ ontologies: Ontology[]; offset: number; limit: number }>(
        `/ontologies?${params}`
      )
    },
    get: (id: string) => request<Ontology>(`/ontologies/${id}`),
    patch: (id: string, shortname: string | null) =>
      request<Ontology>(`/ontologies/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ shortname }),
      }),
    versions: (id: string) =>
      request<{ versions: OntologyVersion[] }>(`/ontologies/${id}/versions`),
    terms: (oid: string, vid: string, parent?: string | null, entityType: 'class' | 'property' | 'object_property' | 'data_property' | 'annotation_property' = 'class', hideInverse = false) => {
      const params = new URLSearchParams({ limit: '200', entity_type: entityType })
      params.set('parent', parent ?? 'root')
      if (hideInverse) params.set('hide_inverse', 'true')
      return request<{ terms: Term[]; offset: number; limit: number; parent: string | null }>(
        `/ontologies/${oid}/${vid}/terms?${params}`
      )
    },
    termDetail: (oid: string, vid: string, iri: string) =>
      request<RawTermDetail>(
        `/ontologies/${oid}/${vid}/terms/${encodeURIComponent(iri)}`
      ),
    search: (oid: string, vid: string, q: string, mode = 'auto') =>
      request<{ mode: string; results: SearchResult[]; count: number; truncated: boolean }>(
        `/ontologies/${oid}/${vid}/search?q=${encodeURIComponent(q)}&mode=${mode}`
      ),
    autocomplete: (oid: string, vid: string, q: string, cursor = -1) =>
      request<AutocompleteResponse>(
        `/ontologies/${oid}/${vid}/autocomplete?q=${encodeURIComponent(q)}&cursor=${cursor}`
      ),
    autocompleteLatest: (oid: string, q: string, cursor = -1) =>
      request<AutocompleteResponse>(
        `/ontologies/${oid}/autocomplete?q=${encodeURIComponent(q)}&cursor=${cursor}`
      ),
    inferredChildren: (oid: string, vid: string, cls = 'http://www.w3.org/2002/07/owl#Thing') =>
      request<{ terms: Term[]; reasoning_available: boolean }>(
        `/ontologies/${oid}/${vid}/inferred-children?cls=${encodeURIComponent(cls)}`
      ),
    ancestors: (oid: string, vid: string, iri: string, mode: 'asserted' | 'inferred' = 'asserted') =>
      request<{ ancestors: Term[]; reasoning_available?: boolean }>(
        `/ontologies/${oid}/${vid}/ancestors?iri=${encodeURIComponent(iri)}&mode=${mode}`
      ),

    ontologyMetadata: (oid: string, vid: string) =>
      request<OntologyDocumentMetadata>(`/ontologies/${oid}/${vid}/ontology-metadata`),

    stats: (oid: string, vid: string) =>
      request<{
        triple_count: number
        class_count: number
        property_count: number
        object_property_count: number
        datatype_property_count: number
        annotation_property_count: number
        individual_count: number
        index_meta: { indexed_at?: string; class_count?: number; property_count?: number }
      }>(`/ontologies/${oid}/${vid}/stats`),

    justification: (oid: string, vid: string, sub: string, sup: string, max = 3) =>
      request<JustificationResult>(
        `/ontologies/${oid}/${vid}/justification?sub=${encodeURIComponent(sub)}&sup=${encodeURIComponent(sup)}&max_justifications=${max}`
      ),

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
    submitFile: (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      return request<{ task_id: string; status: string }>('/ontologies', {
        method: 'POST',
        body: fd,
      })
    },
    submitByContent: (content: string, format?: string) =>
      request<{ task_id: string; status: string }>('/ontologies', {
        method: 'POST',
        body: JSON.stringify({ content, format }),
      }),
    delete: (id: string) =>
      request<void>(`/ontologies/${id}`, { method: 'DELETE' }),
  },

  globalSearch: {
    search: (q: string, limit = 20) => {
      const params = new URLSearchParams({ q, limit: String(limit) })
      return fetch(`/api/v1/search?${params}`)
        .then(r => r.json()) as Promise<{ results: SearchResult[]; count: number; truncated: boolean }>
    },
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
    deliveries: (id: string) =>
      request<{ deliveries: WebhookDelivery[] }>(`/webhooks/${id}/deliveries`),
    create: (url: string, events: string[], secret?: string) =>
      request<Webhook>('/webhooks', {
        method: 'POST',
        body: JSON.stringify({ url, events, secret }),
      }),
    delete: (id: string) => request<void>(`/webhooks/${id}`, { method: 'DELETE' }),
    test: (id: string) =>
      request<{ delivery_id: string; status: string }>(`/webhooks/${id}/test`, { method: 'POST' }),
  },

  stats: {
    get: () =>
      request<{
        total_ontologies: number
        total_versions: number
        storage_bytes: number
        total_queries: number
        uploads_per_month: Array<{ month: string; count: number }>
        queries_per_month: Array<{ month: string; count: number }>
        job_durations: Array<{ month: string; avg_seconds: number }>
      }>('/stats'),
    public: () =>
      request<{ total_ontologies: number; total_classes: number; total_properties: number }>(
        '/stats/public'
      ),
  },
}
