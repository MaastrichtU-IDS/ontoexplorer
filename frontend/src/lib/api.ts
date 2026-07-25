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

// Core request against an ABSOLUTE app path (already including any prefix).
// Handles the bearer header + one refresh-on-401 retry + typed errors.
async function requestUrl<T>(url: string, options: RequestInit = {}): Promise<T> {
  // Cold load / lost in-memory token: bootstrap it from the refresh_token cookie
  // BEFORE sending, so authenticated actions (e.g. uploads, which the backend
  // accepts anonymously and would silently record with no owner) carry the
  // bearer token. Single-flighted in refreshAccessToken, so this is cheap.
  let token = getAccessToken()
  if (!token) token = await refreshAccessToken()
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  }
  // Don't set Content-Type for FormData (let browser set boundary)
  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }
  if (token) headers['Authorization'] = `Bearer ${token}`

  let resp = await fetch(url, { ...options, headers })

  if (resp.status === 401) {
    // Only attempt refresh + redirect if we actually had a session.
    // For anonymous users hitting an auth-required endpoint on a public page,
    // surface the 401 to the caller instead of forcing a redirect to /login.
    if (token) {
      const newToken = await refreshAccessToken()
      if (newToken) {
        headers['Authorization'] = `Bearer ${newToken}`
        resp = await fetch(url, { ...options, headers })
      } else {
        clearAccessToken()
        window.location.href = '/login'
        throw new ApiError('Session expired', 401, null)
      }
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

// Request against the versioned API (routers mounted under /api/v1).
async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  return requestUrl<T>(`${BASE}${path}`, options)
}

// Request against the auth router, which is mounted at /auth (NOT under /api/v1).
async function authRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  return requestUrl<T>(path, options)
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

export interface LangLabel {
  value: string
  lang: string | null
}

export interface OntologyLanguage {
  lang: string
  label_count: number
}

export interface DiffLiteralChange {
  predicate: string
  lang: string | null
  removed: string | null
  added: string | null
}

export interface DiffAxiomChange {
  op: 'added' | 'removed'
  axiom: string
  source: 'asserted' | 'inferred'
}

export type DiffEntityType =
  | 'class'
  | 'object_property'
  | 'data_property'
  | 'annotation_property'
  | 'individual'

export type ManchesterTextToken = { t: 'text'; v: string }
export type ManchesterIriToken  = { t: 'iri'; label: string; iri: string; in_ontology: boolean }
export type ManchesterToken     = ManchesterTextToken | ManchesterIriToken

export type ManchesterLine = {
  op: 'added' | 'removed' | null
  source: 'asserted' | 'inferred' | null
  tokens: ManchesterToken[]
}

export type ManchesterFrame = {
  lines: ManchesterLine[]
}

export interface DiffEntity {
  iri: string
  label: string | null
  entity_type: DiffEntityType
  // Backend omits these fields for added/removed entities — they only appear
  // on modified entities. Renderers must guard.
  literal_changes?: DiffLiteralChange[]
  axiom_changes?: DiffAxiomChange[]
  manchester_frame?: ManchesterFrame | null
}

export interface DiffSummary {
  added: number
  removed: number
  modified: number
  literal_changes: number
  axiom_changes: number
  asserted_axiom_changes: number
  inferred_axiom_changes: number
  by_entity_type: Record<DiffEntityType, { added: number; removed: number; modified: number }>
  inferred_status: {
    from_version: 'ready' | 'pending' | 'failed' | 'missing'
    to_version: 'ready' | 'pending' | 'failed' | 'missing'
  }
}

export interface OntologyDiff {
  status: 'pending' | 'ready' | 'failed'
  summary?: DiffSummary
  diff_data?: {
    added: DiffEntity[]
    removed: DiffEntity[]
    modified: DiffEntity[]
  }
  narrative: string | null
}

export interface OntologyComparison {
  status: 'pending' | 'ready' | 'failed'
  from_ontology_id: string
  to_ontology_id: string
  version_from_id: string
  version_to_id: string
  summary?: DiffSummary
  diff_data?: {
    added: DiffEntity[]
    removed: DiffEntity[]
    modified: DiffEntity[]
  }
}

export interface ComparisonPending {
  status: 'pending' | 'failed'
}

export interface UserProfile {
  id: string
  email: string | null
  display_name: string | null
  created_at: string
  is_admin: boolean
  is_uploader?: boolean
  connected_providers: string[]
  preferred_lang?: string | null
  lang_fallback_strategy?: string
}

export interface MaintainerRequest {
  id: string
  user_id: string
  request_type: 'ontology' | 'uploader'
  ontology_id: string | null
  note: string | null
  status: 'pending' | 'approved' | 'denied'
  decision_note: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  created_at: string
  // decorated fields (present on list responses)
  user_email?: string | null
  user_display_name?: string | null
  ontology_shortname?: string
  ontology_iri?: string
}

export interface Ontology {
  id: string
  iri: string
  shortname: string | null
  title: string | null
  groups?: string[]
  created_at: string
  current_version_id?: string | null
  latest_version?: OntologyVersion | null
  class_count?: number | null
  property_count?: number | null
  object_property_count?: number | null
  datatype_property_count?: number | null
  annotation_property_count?: number | null
  triple_count?: number | null
  individual_count?: number | null
  label?: string | null
  description?: string | null
  preferred_lang?: string | null
  languages?: OntologyLanguage[]
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
  /** Reasoner this version was ingested/classified with (e.g. "whelk",
   *  "rustdl", "konclude"). Look it up in `api.reasoners.list()` to find its
   *  capabilities — e.g. whether it supports `justify`. */
  reasoner?: string | null
}

export interface Term {
  iri: string
  label: string | null
  has_children?: boolean
  source?: string
  lang?: string | null
  /** True when ELK classified this class as unsatisfiable. Frontend
   *  renders it in red (Protégé-style "broken corner"). */
  is_unsatisfiable?: boolean
  /** Only set on the synthetic owl:Nothing root node — the count of unsat classes. */
  unsat_children_count?: number
}

export interface ClassRef {
  iri: string
  label: string
  /** Imported-from source short-name (e.g. 'bfo', 'iao') when the term
   *  originates outside the host ontology. Empty for native terms. */
  source?: string
}

export interface PropertyUsage {
  class_iri: string
  class_label: string
  relation: string
  restriction: string
  filler_iri: string | null
  filler_label: string | null
  /** Recursive expression for an anonymous (blank-node) filler, e.g.
   *  `some (r some X)`. Present instead of filler_iri/label when the filler is
   *  a nested class expression; rendered via ExprNode. */
  filler_expr?: ClassExprNode | null
  /** The whole axiom as Manchester-syntax tokens (clickable IRIs). Preferred
   *  rendering; the flat fields above remain as a fallback. */
  manchester?: ManchesterToken[] | null
}

export interface ClassUsageEntry {
  class_iri: string
  class_label: string
  relation: string
  property_iri: string | null
  property_label: string | null
  restriction: string
  /** The whole axiom as Manchester-syntax tokens (clickable IRIs). */
  manchester?: ManchesterToken[] | null
}

export interface InferredExprEntry {
  expr: ClassExprNode
  from_iri: string
  from_label: string
}

export interface SchemaProperty {
  prop_iri: string
  prop_label: string
  range_iri: string | null
  range_label: string | null
}

export interface InheritedSchemaProperty extends SchemaProperty {
  from_iri: string
  from_label: string
}

export interface RawTermDetail {
  iri: string
  label: string
  source?: string
  properties: Record<string, LangLabel[]>
  /** Human-readable label for each predicate IRI used by this term —
   *  joined from entity_index. Empty/missing entries fall back to a
   *  well-known static table, then to the IRI fragment. */
  property_labels?: Record<string, string>
  /** Predicate IRI -> its OWL entity type (object_property / data_property /
   *  annotation_property) from entity_index. Missing for unindexed predicates. */
  property_types?: Record<string, string>
  labels?: LangLabel[]
  definitions?: LangLabel[]
  elucidations?: LangLabel[]
  synonyms?: LangLabel[]
  lang?: string | null
  type_of?: ClassRef[]
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
  usage_has_more?: boolean
  class_usage?: ClassUsageEntry[]
  class_usage_has_more?: boolean
  schema_properties?: SchemaProperty[]
  inherited_schema_properties?: InheritedSchemaProperty[]
}

export interface ParsedTerm {
  iri: string
  label: string
  source?: string
  definition: string | null
  entityType: 'class' | 'property' | 'object_property' | 'data_property' | 'annotation_property' | 'individual'
  isInverseTarget: boolean
  typeOf: ClassRef[]
  rawProperties: Record<string, LangLabel[]>
  propertyLabels: Record<string, string>
  propertyTypes: Record<string, string>
  rawLabels: LangLabel[]
  rawDefinitions: LangLabel[]
  rawElucidations: LangLabel[]
  rawSynonyms: LangLabel[]
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
  usageHasMore?: boolean
  classUsage: ClassUsageEntry[]
  classUsageHasMore?: boolean
  schemaProperties: SchemaProperty[]
  inheritedSchemaProperties: InheritedSchemaProperty[]
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
  | { type: 'datatype_restriction'; datatype: ClassExprNode; facets: { facet: string; value: string }[] }
  | { type: 'unknown' }

export interface SearchResult {
  iri: string
  label: string
  short: string
  type?: string
  source?: string
  match_type: 'entity' | 'elk' | 'sparql' | 'semantic'
  score?: number
  version_id?: string
  ontology_id?: string
  lang?: string | null
  cross_language?: boolean
}

export interface JustificationResult {
  /** Each justification is a list of Manchester-syntax axiom strings (one
   *  reasoning step per line). Uniform across reasoners (whelk, rustdl, …) —
   *  see `format`. */
  justifications: string[][]
  format: string
  timed_out: boolean
  reasoning_available: boolean
  /** IRI→display-label for every IRI mentioned in `justifications`, resolved
   *  server-side from the ontology's label index (incl. OBO labels). Lets the
   *  UI render clickable, human-readable entity tokens. */
  labels?: Record<string, string>
}

export interface ReasonerInfo {
  name: string
  profile: string
  capabilities: string[]
  available: boolean
}

export interface AutocompleteCompletion {
  text: string
  type: string
  iri: string | null
  short: string | null
  insert: string
  lang?: string | null
  cross_language?: boolean
  ontology_shortname?: string | null
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

export interface SavedQuery {
  id: string
  user_id: string
  name: string
  description: string | null
  query_text: string
  tags: string[]
  is_public: boolean
  created_at: string
  updated_at: string
  user_display_name?: string
}

export interface StarterQuery {
  id: string
  name: string
  description: string | null
  category: string | null
  tags: string[]
  query_text: string
  is_starter: boolean
  is_public: boolean
  created_at: string | null
  updated_at: string | null
}

export type ImportStartersPayload =
  | { text: string }
  | { source_url: string }
  | { file: File }

export interface ImportStartersResponse {
  created: number
  skipped: number
  errors: Array<{ index: number; name?: string; reason: string }>
}

// ── Profile types ─────────────────────────────────────────────────────────────

export interface OntologyProfileData {
  version_id: string
  label_props: string[]
  definition_props: string[]
  elucidation_props: string[]
  synonym_props: string[]
  deprecated_props: string[]
  example_props: string[]
  status: 'auto_detected' | 'user_confirmed'
  updated_at: string | null
}

export interface ProfileCandidate {
  iri: string
  count: number
  mod_declared: boolean
  label?: string | null
}

export interface ProfileUnknown {
  iri: string
  count: number
  pct_of_classes: number
  label?: string | null
}

export interface ProfileCandidates {
  version_id: string
  label: ProfileCandidate[]
  definition: ProfileCandidate[]
  synonym: ProfileCandidate[]
  deprecated: ProfileCandidate[]
  unknown: ProfileUnknown[]
}

export interface ProfilePatch {
  label_props?: string[]
  definition_props?: string[]
  elucidation_props?: string[]
  synonym_props?: string[]
  deprecated_props?: string[]
  example_props?: string[]
}

// ── Meta-profile types ────────────────────────────────────────────────────────

export interface OntologyMetaResolved {
  title: string | null
  shortname: string | null
  description: string | null
  creators: string[]
  contributors: string[]
  publishers: string[]
  license: string | null
  homepage: string | null
  version_info: string | null
  version_iri: string | null
  prefix: string | null
  namespace_uri: string | null
  created: string | null
  modified: string | null
  language: string | null
  citation: string | null
  funding: string | null
  status: string | null
  syntax: string | null
  see_also: string[]
  is_defined_by: string | null
  competency_questions: string[]
  endorsed_by: string[]
  relies_on: string[]
  similar: string[]
  generalizes: string[]
  specializes: string[]
  known_usage: string[]
  used_in_project: string[]
}

export interface OntologyMetaProfile {
  version_id: string
  title_props: string[]
  shortname_props: string[]
  description_props: string[]
  creator_props: string[]
  contributor_props: string[]
  publisher_props: string[]
  license_props: string[]
  homepage_props: string[]
  version_info_props: string[]
  version_iri_props: string[]
  prefix_props: string[]
  namespace_uri_props: string[]
  created_props: string[]
  modified_props: string[]
  language_props: string[]
  citation_props: string[]
  funding_props: string[]
  status_props: string[]
  syntax_props: string[]
  see_also_props: string[]
  is_defined_by_props: string[]
  competency_question_props: string[]
  endorsed_by_props: string[]
  relies_on_props: string[]
  similar_props: string[]
  generalizes_props: string[]
  specializes_props: string[]
  known_usage_props: string[]
  used_in_project_props: string[]
  resolved: OntologyMetaResolved
  status: 'auto_detected' | 'user_confirmed'
  updated_at: string | null
}

export interface MetaProfilePatch {
  title_props?: string[]
  shortname_props?: string[]
  description_props?: string[]
  creator_props?: string[]
  contributor_props?: string[]
  publisher_props?: string[]
  license_props?: string[]
  homepage_props?: string[]
  version_info_props?: string[]
  version_iri_props?: string[]
  prefix_props?: string[]
  namespace_uri_props?: string[]
  created_props?: string[]
  modified_props?: string[]
  language_props?: string[]
  citation_props?: string[]
  funding_props?: string[]
  status_props?: string[]
  syntax_props?: string[]
  see_also_props?: string[]
  is_defined_by_props?: string[]
  competency_question_props?: string[]
  endorsed_by_props?: string[]
  relies_on_props?: string[]
  similar_props?: string[]
  generalizes_props?: string[]
  specializes_props?: string[]
  known_usage_props?: string[]
  used_in_project_props?: string[]
}

export interface BulkMetaItem extends OntologyMetaResolved {
  ontology_id: string
  version_id: string
  profile_status: string
}

// ── OWL 2 profile types ───────────────────────────────────────────────────────

export type ProfileName = 'el' | 'rl' | 'ql' | 'dl'

export interface ProfileSampleViolation {
  axiom_type: string
  subject_iri?: string
  details?: string
  /** Pre-rendered Manchester OWL tokens. Present after reindex with Manchester support. */
  manchester?: ManchesterToken[] | null
}

export interface ProfileResult {
  in_profile: boolean
  total_violations: number
  violations_by_axiom_type: Record<string, number>
  sample_violations: ProfileSampleViolation[]
}

export interface OwlProfileRecord {
  el: ProfileResult
  rl: ProfileResult
  ql: ProfileResult
  dl: ProfileResult
  indexed_at: string
}

export interface OwlProfileFleetEntry {
  id: string
  shortname?: string | null
  title?: string | null
  version_id: string
  in_el: boolean
  in_rl: boolean
  in_ql: boolean
  in_dl: boolean
  el_violations: number
  rl_violations: number
  ql_violations: number
  dl_violations: number
}

export interface OwlProfileFleet {
  ontologies: OwlProfileFleetEntry[]
  totals: {
    fleet_size: number
    el_count: number
    rl_count: number
    ql_count: number
    dl_count: number
  }
}

// ── Reuse types ───────────────────────────────────────────────────────────────

export type ImportEdge = {
  target_iri: string
  target_prefix: string | null
  depth: number
  resolved: boolean
}

export type TermIRIReuseEntry = {
  class_count: number
  property_count: number
  sample_iris: string[]
  resolved: boolean
}

export type MireotTerm = {
  iri: string
  source_prefix: string
  has_imported_from: boolean
}

export type MappingEntry = {
  target_prefix: string | null
  count: number
  sample_pairs: [string, string][]
}

export type ReuseReport = {
  version_id: string
  host_prefix: string | null
  host_iri: string
  imports: ImportEdge[]
  term_iri_reuse: Record<string, TermIRIReuseEntry>
  mireot_terms: MireotTerm[]
  mappings: Record<string, MappingEntry[]>
  indexed_at: string
}

export type ReuseFleetEntry = {
  id: string
  shortname: string
  title: string
  version_id: string
  imports_count: number
  mireot_terms_count: number
  term_iri_reused_count: number
  mappings_count: number
  source_prefixes: string[]
}

export type ReuseFleet = {
  ontologies: ReuseFleetEntry[]
  totals: {
    fleet_size: number
    total_import_edges: number
    total_mireot_terms: number
    ontologies_with_mireot: number
  }
  top_reused_sources: { prefix: string; reusers_count: number }[]
}

// ── Coverage types ────────────────────────────────────────────────────────────

export type CoverageEntityType =
  | 'class'
  | 'object_property'
  | 'data_property'
  | 'annotation_property'
  | 'individual'

export interface CoverageBucket {
  total: number
  with_label: number
  with_definition: number
  multilingual: number
  by_lang: Record<string, number>
}

export interface CoverageBucketCompact {
  total: number
  with_label: number
  with_definition: number
  multilingual: number
}

export interface CoverageRecord {
  version_id: string
  indexed_at: string
  by_type: Record<CoverageEntityType, CoverageBucket>
}

export interface CoverageFleetEntry {
  ontology_id: string
  version_id: string
  shortname: string | null
  title: string | null
  indexed_at: string
  by_type: Record<CoverageEntityType, CoverageBucketCompact>
}

export interface CoverageFleet {
  totals: Record<CoverageEntityType, CoverageBucketCompact>
  by_ontology: CoverageFleetEntry[]
}

// ── Admin types ───────────────────────────────────────────────────────────────

export interface AdminServiceStatus {
  postgres: string
  redis: string
  minio: string
  elk: string
  fuseki: string
  oxigraph: string
  workers: string
  beat: string
  entity_index: string
  entity_index_rows: number
  entity_index_drift: { version_id: string; redis: number; pg: number }[]
  celery_queue_depth: number
}

export interface AdminOntologyEntry {
  id: string
  iri: string
  shortname: string | null
  label: string | null
  source_url: string | null
  current_version_id: string | null
  version_id: string
  version_iri: string | null
  version_count: number
  triple_count: number | null
  ingestion_status: string
  indexed: boolean
  profile_computed: boolean
  embed_count: number
  reasoning_status: 'ready' | 'running' | 'not_started'
  version_created_at: string | null
}

export interface AdminJobEntry {
  id: string
  type: string
  version_id: string
  ontology_shortname: string | null
  ontology_iri: string | null
  status: string
  started_at: string | null
  finished_at: string | null
  error: string | null
}

export interface AdminOverview {
  services: AdminServiceStatus
  ontologies: AdminOntologyEntry[]
  jobs: AdminJobEntry[]
}

export interface AdminVersionEntry {
  version_id: string
  version_iri: string | null
  triple_count: number | null
  ingestion_status: string
  indexed: boolean
  profile_computed: boolean
  embed_count: number
  reasoning_status: 'ready' | 'running' | 'not_started'
  version_created_at: string | null
  source_url: string | null
  is_latest: boolean
  diff_vs_prev: {
    previous_version_id: string | null
    status: 'ready' | 'running' | 'pending' | 'failed' | 'missing' | 'stale'
    diff_id: string | null
    computed_at: string | null
  }
}

export interface AdminVersionsResponse {
  ontology_id: string
  versions: AdminVersionEntry[]
}

export interface WorkerTask {
  id: string
  name: string
  state: 'active' | 'reserved' | 'pending'
  kwargs: Record<string, unknown>
  time_start: number | null
  worker: string
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
  // Extract string value from LangLabel for backward compat
  const getValues = (pred: string): string[] => (p[pred] ?? []).map(e => e.value)
  const getFirst = (pred: string): string | null => p[pred]?.[0]?.value ?? null

  const label = getFirst(P.label) ?? raw.iri.split(/[#/]/).pop() ?? raw.iri
  const definition = getFirst(P.definition) ?? getFirst(P.comment)
  const types = getValues(P.type)
  let entityType: ParsedTerm['entityType'] = 'class'
  if (types.includes(P.owlObjProp)) {
    entityType = 'object_property'
  } else if (types.includes(P.owlDataProp)) {
    entityType = 'data_property'
  } else if (types.includes(P.owlAnnProp)) {
    entityType = 'annotation_property'
  } else if (types.includes(P.owlIndividual)) {
    entityType = 'individual'
  } else if (types.includes('http://www.w3.org/1999/02/22-rdf-syntax-ns#Property')) {
    entityType = 'property'
  }
  const characteristics = types.map(t => OWL_CHARACTERISTICS[t]).filter(Boolean) as string[]
  return {
    iri: raw.iri,
    label: raw.label ?? label,
    source: raw.source ?? '',
    definition,
    entityType,
    isInverseTarget: raw.is_inverse_target ?? false,
    typeOf: raw.type_of ?? [],
    rawProperties: raw.properties,
    propertyLabels: raw.property_labels ?? {},
    propertyTypes: raw.property_types ?? {},
    rawLabels: raw.labels ?? [],
    rawDefinitions: raw.definitions ?? [],
    rawElucidations: raw.elucidations ?? [],
    rawSynonyms: raw.synonyms ?? [],
    synonyms: {
      exact:   getValues(P.exactSyn),
      related: getValues(P.relatedSyn),
      broad:   getValues(P.broadSyn),
      narrow:  getValues(P.narrowSyn),
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
    domain:               [...new Set([...getValues(P.domain), ...getValues('https://schema.org/domainIncludes')])],
    range:                [...new Set([...getValues(P.range),  ...getValues('https://schema.org/rangeIncludes')])],
    characteristics,
    inverseOf:            getValues(P.inverseOf),
    usage:           raw.usage        ?? [],
    usageHasMore:    raw.usage_has_more,
    classUsage:      raw.class_usage  ?? [],
    classUsageHasMore: raw.class_usage_has_more,
    schemaProperties:          raw.schema_properties           ?? [],
    inheritedSchemaProperties: raw.inherited_schema_properties ?? [],
  }
}

// ── API surface ───────────────────────────────────────────────────────────────

export const api = {
  auth: {
    // NOTE: the auth router is mounted at /auth (NOT under /api/v1), so these use
    // authRequest (no BASE prefix), not request.
    me: async () => {
      // Cold loads (page refresh, or returning from an OAuth link/merge
      // round-trip) have no in-memory access token — the login cookie is
      // single-use. Restore the session from the httpOnly refresh_token cookie
      // before calling /auth/me, so the user isn't shown as logged out.
      if (!getAccessToken()) await refreshAccessToken()
      return authFetch<UserProfile>('/auth/me')
    },
    patchMe: (body: { preferred_lang?: string | null; lang_fallback_strategy?: string; display_name?: string }) =>
      authRequest<UserProfile>('/auth/me', {
        method: 'PATCH',
        body: JSON.stringify(body),
      }),
    // Start linking a provider to the current account — returns the OAuth
    // authorize URL to redirect the browser to (see loginWithProvider/linkProvider).
    linkStart: (provider: 'orcid' | 'github' | 'google') =>
      authRequest<{ authorize_url: string }>(`/auth/${provider}/link`),
    unlink: (provider: 'orcid' | 'github' | 'google') =>
      authRequest<{ connected_providers: string[] }>(`/auth/${provider}/unlink`, { method: 'POST' }),
    // Confirm merging another account (identified by the signed token that
    // /callback handed back via ?merge_available) into the current one.
    merge: (token: string) =>
      authRequest<{ moved: Record<string, number>; connected_providers: string[] }>('/auth/merge', {
        method: 'POST',
        body: JSON.stringify({ token }),
      }),
  },

  maintainers: {
    // Request a maintainer role: over an existing ontology, or global upload rights.
    request: (body: { request_type: 'ontology' | 'uploader'; ontology_id?: string; note?: string }) =>
      request<MaintainerRequest>('/maintainer-requests', {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    mine: () => request<{ requests: MaintainerRequest[] }>('/maintainer-requests'),
  },

  ontologies: {
    list: (offset = 0, limit = 50, q?: string, group?: string, profile?: ProfileName, reuses?: string) => {
      const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
      if (q) params.set('q', q)
      if (group) params.set('group', group)   // single group filter sent to API
      if (profile) params.set('profile', profile)
      if (reuses) params.set('reuses', reuses)
      return request<{ ontologies: Ontology[]; offset: number; limit: number }>(
        `/ontologies?${params}`
      )
    },
    get: (id: string) => request<Ontology>(`/ontologies/${id}`),
    patch: (id: string, body: { shortname?: string | null; title?: string | null; preferred_lang?: string | null; groups?: string[]; current_version_id?: string | null }) =>
      request<Ontology>(`/ontologies/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      }),
    versions: (id: string) =>
      request<{ versions: OntologyVersion[] }>(`/ontologies/${id}/versions`),
    terms: (oid: string, vid: string, parent?: string | null, entityType: 'class' | 'property' | 'object_property' | 'data_property' | 'annotation_property' | 'individual' = 'class', hideInverse = false, hideObsolete = true, limit = 200, offset = 0, lang?: string | null) => {
      const params = new URLSearchParams({ limit: String(limit), offset: String(offset), entity_type: entityType })
      params.set('parent', parent ?? 'root')
      if (hideInverse) params.set('hide_inverse', 'true')
      if (!hideObsolete) params.set('hide_obsolete', 'false')
      if (lang) params.set('lang', lang)
      return request<{ terms: Term[]; offset: number; limit: number; parent: string | null }>(
        `/ontologies/${oid}/${vid}/terms?${params}`
      )
    },
    termDetail: (oid: string, vid: string, iri: string, lang?: string) =>
      request<RawTermDetail>(
        `/ontologies/${oid}/${vid}/terms/${encodeURIComponent(iri)}${lang ? `?lang=${lang}` : ''}`
      ),
    termExpanded: (oid: string, vid: string, iri: string, lang?: string) =>
      request<{
        inferred_superclass_expressions: InferredExprEntry[]
        inferred_disjoint_with: InferredExprEntry[]
        inherited_schema_properties: InheritedSchemaProperty[]
      }>(
        `/ontologies/${oid}/${vid}/term-expanded/${encodeURIComponent(iri)}${lang ? `?lang=${lang}` : ''}`
      ),
    termUsagePage: (oid: string, vid: string, iri: string, offset: number, limit = 20) =>
      request<{
        kind: 'property' | 'class'
        offset: number
        limit: number
        items: PropertyUsage[] | ClassUsageEntry[]
        has_more: boolean
      }>(
        `/ontologies/${oid}/${vid}/term-usage/${encodeURIComponent(iri)}?offset=${offset}&limit=${limit}`
      ),
    search: (oid: string, vid: string, q: string, mode = 'auto', lang?: string, semantic = false, direct = false, relation = 'subclasses') =>
      request<{
        mode: string
        results: SearchResult[]
        count: number
        truncated: boolean
        semantic_results?: SearchResult[]
      }>(
        `/ontologies/${oid}/${vid}/search?q=${encodeURIComponent(q)}&mode=${mode}${lang ? `&lang=${lang}` : ''}${semantic ? '&semantic=true' : ''}${direct ? '&direct=true' : ''}${relation !== 'subclasses' ? `&relation=${relation}` : ''}`
      ),
    autocomplete: (oid: string, vid: string, q: string, cursor = -1, lang?: string) =>
      request<AutocompleteResponse>(
        `/ontologies/${oid}/${vid}/autocomplete?q=${encodeURIComponent(q)}&cursor=${cursor}${lang ? `&lang=${lang}` : ''}`
      ),
    languages: (oid: string, vid: string) =>
      request<OntologyLanguage[]>(`/ontologies/${oid}/${vid}/languages`),
    diff: (ontologyId: string, versionId: string) =>
      request<OntologyDiff>(`/ontologies/${ontologyId}/${versionId}/diff`),
    diffArbitrary: (ontologyId: string, fromVid: string, toVid: string) =>
      request<OntologyDiff>(
        `/ontologies/${ontologyId}/diff?from=${encodeURIComponent(fromVid)}&to=${encodeURIComponent(toVid)}`
      ),
    generateNarrative: (ontologyId: string, versionId: string) =>
      request<{ narrative: string }>(
        `/ontologies/${ontologyId}/${versionId}/diff/narrative`,
        { method: 'POST' }
      ),
    autocompleteLatest: (oid: string, q: string, cursor = -1) =>
      request<AutocompleteResponse>(
        `/ontologies/${oid}/autocomplete?q=${encodeURIComponent(q)}&cursor=${cursor}`
      ),
    inferredChildren: (oid: string, vid: string, cls = 'http://www.w3.org/2002/07/owl#Thing', lang?: string | null, hideObsolete = true) => {
      const params = new URLSearchParams({ cls })
      if (lang) params.set('lang', lang)
      if (!hideObsolete) params.set('hide_obsolete', 'false')
      return request<{ terms: Term[]; reasoning_available: boolean }>(
        `/ontologies/${oid}/${vid}/inferred-children?${params}`
      )
    },
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

    submitByIri: (iri: string, reasoner?: string) =>
      request<{ task_id: string; status: string }>('/ontologies', {
        method: 'POST',
        body: JSON.stringify({ iri, ...(reasoner ? { reasoner } : {}) }),
      }),
    submitByUrl: (url: string, reasoner?: string) =>
      request<{ task_id: string; status: string }>('/ontologies', {
        method: 'POST',
        body: JSON.stringify({ url, ...(reasoner ? { reasoner } : {}) }),
      }),
    submitFile: (file: File, reasoner?: string) => {
      const fd = new FormData()
      fd.append('file', file)
      if (reasoner) fd.append('reasoner', reasoner)
      return request<{ task_id: string; status: string }>('/ontologies', {
        method: 'POST',
        body: fd,
      })
    },
    submitByContent: (content: string, format?: string, reasoner?: string) =>
      request<{ task_id: string; status: string }>('/ontologies', {
        method: 'POST',
        body: JSON.stringify({ content, format, ...(reasoner ? { reasoner } : {}) }),
      }),
    delete: (id: string) =>
      request<void>(`/ontologies/${id}`, { method: 'DELETE' }),

    profile: {
      get: (ontologyId: string, versionId: string) =>
        request<OntologyProfileData>(`/ontologies/${ontologyId}/${versionId}/profile`),
      patch: (ontologyId: string, versionId: string, body: ProfilePatch) =>
        request<OntologyProfileData>(`/ontologies/${ontologyId}/${versionId}/profile`, {
          method: 'PATCH',
          body: JSON.stringify(body),
        }),
      detect: (ontologyId: string, versionId: string) =>
        request<OntologyProfileData>(
          `/ontologies/${ontologyId}/${versionId}/profile/detect`,
          { method: 'POST' }
        ),
      candidates: (ontologyId: string, versionId: string) =>
        request<ProfileCandidates>(`/ontologies/${ontologyId}/${versionId}/profile/candidates`),
    },

    meta: {
      get: (ontologyId: string, versionId: string) =>
        request<OntologyMetaProfile>(`/ontologies/${ontologyId}/${versionId}/meta`),
      patch: (ontologyId: string, versionId: string, body: MetaProfilePatch) =>
        request<OntologyMetaProfile>(`/ontologies/${ontologyId}/${versionId}/meta`, {
          method: 'PATCH',
          body: JSON.stringify(body),
        }),
      detect: (ontologyId: string, versionId: string) =>
        request<OntologyMetaProfile>(
          `/ontologies/${ontologyId}/${versionId}/meta/detect`,
          { method: 'POST' }
        ),
      candidates: (ontologyId: string, versionId: string) =>
        request<{ version_id: string; [key: string]: unknown }>(
          `/ontologies/${ontologyId}/${versionId}/meta/candidates`
        ),
    },

    reuse: (ontologyId: string, versionId: string) =>
      request<ReuseReport>(`/ontologies/${ontologyId}/${versionId}/reuse`),
  },

  globalSearch: {
    search: (q: string, limit = 20, semantic = false, types: string[] = []) => {
      const params = new URLSearchParams({ q, limit: String(limit) })
      if (semantic) params.set('semantic', 'true')
      types.forEach(t => params.append('types', t))
      return fetch(`/api/v1/search?${params}`)
        .then(r => r.json()) as Promise<{
          results: SearchResult[]
          count: number
          truncated: boolean
          semantic_results?: SearchResult[]
        }>
    },
    autocomplete: (q: string, cursor = -1, ontologyIds: string[] = []) => {
      const params = new URLSearchParams({ q, cursor: String(cursor) })
      ontologyIds.forEach(id => params.append('ontology_ids', id))
      return request<AutocompleteResponse>(`/autocomplete?${params}`)
    },
  },

  languages: {
    list: () => request<OntologyLanguage[]>('/languages'),
  },

  reasoners: {
    list: () => request<ReasonerInfo[]>('/reasoners'),
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

  savedQueries: {
    create: (body: { name: string; description?: string; query_text: string; tags: string[]; is_public: boolean }) =>
      request<SavedQuery>('/sparql/queries', { method: 'POST', body: JSON.stringify(body) }),

    list: () =>
      request<{ queries: SavedQuery[] }>('/sparql/queries'),

    listPublic: (params: { q?: string; ontology?: string; user_id?: string; limit?: number; offset?: number }) => {
      const p = new URLSearchParams()
      if (params.q) p.set('q', params.q)
      if (params.ontology) p.set('ontology', params.ontology)
      if (params.user_id) p.set('user_id', params.user_id)
      if (params.limit !== undefined) p.set('limit', String(params.limit))
      if (params.offset !== undefined) p.set('offset', String(params.offset))
      return request<{ queries: SavedQuery[]; total: number }>(`/sparql/queries/public?${p}`)
    },

    get: (id: string) =>
      request<SavedQuery>(`/sparql/queries/${id}`),

    update: (id: string, body: Partial<{ name: string; description: string; query_text: string; tags: string[]; is_public: boolean }>) =>
      request<SavedQuery>(`/sparql/queries/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),

    delete: (id: string) =>
      request<void>(`/sparql/queries/${id}`, { method: 'DELETE' }),

    listStarters: () =>
      request<{ starters: StarterQuery[] }>('/sparql/starters'),
  },

  coverage: {
    fleet: () => request<CoverageFleet>('/coverage/public'),
    version: (ontologyId: string, versionId: string) =>
      request<CoverageRecord>(`/ontologies/${ontologyId}/${versionId}/coverage`),
  },

  owl_profile: {
    fleet: () => request<OwlProfileFleet>('/owl-profile/public'),
    version: (ontologyId: string, versionId: string) =>
      request<OwlProfileRecord>(`/ontologies/${ontologyId}/${versionId}/owl-profile`),
  },

  reuse: {
    fleet: () => request<ReuseFleet>('/reuse/fleet'),
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
      request<{
        total_ontologies: number
        total_classes: number
        unique_classes: number
        total_object_properties: number
        unique_object_properties: number
        total_data_properties: number
        unique_data_properties: number
        total_annotation_properties: number
        unique_annotation_properties: number
        total_axioms: number
        total_individuals: number
        unique_individuals: number
      }>('/stats/public'),
  },

  admin: {
    overview: () => request<AdminOverview>('/admin/overview'),
    maintainerRequests: (status?: string) =>
      request<{ requests: MaintainerRequest[] }>(
        `/admin/maintainer-requests${status ? `?status=${encodeURIComponent(status)}` : ''}`,
      ),
    approveMaintainerRequest: (id: string, note?: string) =>
      request<MaintainerRequest>(`/admin/maintainer-requests/${id}/approve`, {
        method: 'POST', body: JSON.stringify({ note: note ?? null }),
      }),
    denyMaintainerRequest: (id: string, note?: string) =>
      request<MaintainerRequest>(`/admin/maintainer-requests/${id}/deny`, {
        method: 'POST', body: JSON.stringify({ note: note ?? null }),
      }),
    checkUpdate: (ontologyId: string) =>
      request<{ status: 'up_to_date' | 'update_queued' | 'no_source_url'; task_id?: string }>(
        `/admin/ontologies/${ontologyId}/check-update`,
        { method: 'POST' }
      ),
    workers: () => request<{ tasks: WorkerTask[] }>('/admin/workers'),
    revokeWorker: (taskId: string, versionId?: string) => {
      const params = versionId ? `?version_id=${encodeURIComponent(versionId)}` : ''
      return request<{ status: string; task_id: string }>(`/admin/workers/${taskId}${params}`, { method: 'DELETE' })
    },
    queueIngest: (ontologyId: string) =>
      request<{ status: string; task_id: string; method: 'iri' | 'url' }>(
        `/admin/ontologies/${ontologyId}/ingest`,
        { method: 'POST' }
      ),
    queueIndex: (ontologyId: string) =>
      request<{ status: string; task_id: string }>(
        `/admin/ontologies/${ontologyId}/index`,
        { method: 'POST' }
      ),
    queueEmbed: (ontologyId: string) =>
      request<{ status: string; task_id: string }>(
        `/admin/ontologies/${ontologyId}/embed`,
        { method: 'POST' }
      ),
    queueReason: (ontologyId: string) =>
      request<{ status: string; task_id: string }>(
        `/admin/ontologies/${ontologyId}/reason`,
        { method: 'POST' }
      ),
    queueDetectProfile: (ontologyId: string) =>
      request<{ status: string; task_id: string }>(
        `/admin/ontologies/${ontologyId}/detect-profile`,
        { method: 'POST' }
      ),
    reindexAll: () =>
      request<{ index_queued: number; meta_detection_queued: number; message: string }>(
        `/admin/reindex`,
        { method: 'POST' }
      ),

    clearJobs: () =>
      request<{ deleted: number }>(`/admin/jobs`, { method: 'DELETE' }),

    versions: (ontologyId: string) =>
      request<AdminVersionsResponse>(`/admin/ontologies/${ontologyId}/versions`),

    queueIndexForVersion: (versionId: string) =>
      request<{ status: string; task_id: string }>(
        `/admin/versions/${versionId}/index`,
        { method: 'POST' }
      ),

    queueEmbedForVersion: (versionId: string) =>
      request<{ status: string; task_id: string }>(
        `/admin/versions/${versionId}/embed`,
        { method: 'POST' }
      ),

    queueReasonForVersion: (versionId: string) =>
      request<{ status: string; task_id: string }>(
        `/admin/versions/${versionId}/reason`,
        { method: 'POST' }
      ),

    queueDetectProfileForVersion: (versionId: string) =>
      request<{ status: string; task_id: string }>(
        `/admin/versions/${versionId}/detect-profile`,
        { method: 'POST' }
      ),

    queueIngestForVersion: (versionId: string) =>
      request<{ status: string; task_id: string; method: 'iri' | 'url' }>(
        `/admin/versions/${versionId}/ingest`,
        { method: 'POST' }
      ),

    queueDiff: (fromVersionId: string, toVersionId: string) =>
      request<{ status: string; task_id: string }>(
        `/admin/diffs/queue`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ from_version_id: fromVersionId, to_version_id: toVersionId }),
        }
      ),

    recomputeAllDiffs: (ontologyId: string) =>
      request<{ queued: number }>(
        `/admin/ontologies/${ontologyId}/diffs/recompute-all`,
        { method: 'POST' }
      ),

    importStarters: (payload: ImportStartersPayload): Promise<ImportStartersResponse> => {
      const form = new FormData()
      if ('file' in payload) {
        form.append('file', payload.file)
      } else if ('source_url' in payload) {
        form.append('source_url', payload.source_url)
      } else {
        form.append('text', payload.text)
      }
      return request<ImportStartersResponse>('/sparql/starters/import', {
        method: 'POST',
        body: form,
      })
    },
  },

  meta: {
    bulk: (ids: string[]) =>
      request<BulkMetaItem[]>(`/meta?ids=${ids.join(',')}`),
  },

  compare: {
    get: (fromVid: string, toVid: string) =>
      request<OntologyComparison | ComparisonPending>(
        `/compare?from_version_id=${encodeURIComponent(fromVid)}&to_version_id=${encodeURIComponent(toVid)}`
      ),
    compute: (fromVid: string, toVid: string) =>
      request<{ status: string }>(
        `/compare/compute?from_version_id=${encodeURIComponent(fromVid)}&to_version_id=${encodeURIComponent(toVid)}`,
        { method: 'POST' }
      ),
  },
}
