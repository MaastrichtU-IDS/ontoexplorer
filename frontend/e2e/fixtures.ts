// Real ontologies on the dev instance, spanning the size spectrum (entity counts
// measured 2026-09-24). All are `ready` (searchable) and reasoned (inferred tree
// available), so they exercise both the asserted and inferred navigation paths.
// Override with E2E_ONTOLOGIES="bfo:57,mondo:59269" if the fixtures drift.
export interface OntoFixture {
  slug: string        // URL segment: /ontologies/<slug>
  label: string
  entities: number    // entity_index rows — the practical "size"
  size: 'tiny' | 'small' | 'medium' | 'large' | 'giant'
}

export const ONTOLOGIES: OntoFixture[] = parseOverride() ?? [
  { slug: 'bfo', label: 'Basic Formal Ontology', entities: 57, size: 'tiny' },
  { slug: 'sio', label: 'Semanticscience Integrated Ontology', entities: 1754, size: 'small' },
  { slug: 'pato', label: 'Phenotype And Trait Ontology', entities: 7978, size: 'medium' },
  { slug: 'uberon', label: 'Uberon', entities: 25854, size: 'large' },
  { slug: 'mondo', label: 'Mondo Disease Ontology', entities: 59269, size: 'giant' },
]

// The one flow set is run against a representative subset to keep wall-clock sane
// while still covering tiny vs giant. Perf specs iterate all ONTOLOGIES.
export const REPRESENTATIVE = ['bfo', 'pato', 'mondo']

export const ROUTES = {
  home: '/',
  ontologies: '/ontologies',
  ontology: (slug: string) => `/ontologies/${slug}`,
  search: '/search',
  sparql: '/sparql',
} as const

// Common vs rare search terms — recall + latency differ.
export const SEARCH_TERMS = { common: 'cell', rare: 'apoptotic process', empty: 'zzqxnope' }

// ── Whole-site route coverage ─────────────────────────────────────────────────
// Static/markdown content pages — rendered by MarkdownPage, where the leading
// `#` heading in the source .md becomes the page <h1>. `heading` is that H1.
export const CONTENT_PAGES = [
  { name: 'about', url: '/about', heading: /About OntoExplorer/i },
  { name: 'docs', url: '/docs', heading: /OntoExplorer documentation/i },
  { name: 'privacy', url: '/privacy', heading: /Privacy & data notice/i },
  { name: 'contact', url: '/contact', heading: /^Contact/i },
] as const

// Login page — the single platform-account sign-in path (#368).
export const LOGIN = { url: '/login', heading: /Sign in to OntoExplorer/i } as const

// Entity browser and the SPARQL query gallery — public, previously untested.
export const BROWSE = { url: '/browse', heading: /Browse entities/i } as const
export const SPARQL_GALLERY = { url: '/sparql/gallery', heading: /Query Gallery/i } as const

// Pure client-side redirects: `from` must land on a URL matching `to`.
export const REDIRECTS = [
  { from: '/coverage', to: /\/ontologies\?tab=coverage/ },
  { from: '/owl-profile', to: /\/ontologies\?tab=profiles/ },
] as const

// OntologyPage right-pane detail tabs. `button` is the tab control's accessible
// name; `ready` is text that proves the tab's content actually mounted (not just
// that the button highlighted). `api` is the endpoint fragment the tab fetches,
// used to confirm the data call fired. History/compare is covered by compare.spec.
export const ONTOLOGY_TABS = [
  { key: 'coverage', button: /^coverage$/i, ready: /Coverage/i, api: /coverage/ },
  { key: 'owl-profile', button: /^owl profile$/i, ready: /Profile & expressivity/i, api: /owl.?profile|profile/ },
  { key: 'reuse', button: /^reuse$/i, ready: /Term-IRI reuse/i, api: /reuse/ },
  { key: 'fair', button: /^fair$/i, ready: /FAIR report/i, api: /fair|score/ },
] as const

// A fully-profiled, reasoned, small ontology: every per-version metric (coverage,
// owl-profile, reuse, FAIR + documentation breakdown) is computed for it, so the
// feature tabs render real content rather than an empty/"pending" state.
export const FEATURE_ONTOLOGY = 'sio'

// Authenticated dashboard routes. AuthGuard redirects each to /login when there
// is no session; with a session each renders its own page. `ready` is a stable
// marker on the loaded page (heading or nav landmark).
export const DASHBOARD_ROUTES = [
  { name: 'dashboard', url: '/dashboard' },
  { name: 'add', url: '/dashboard/add' },
  { name: 'submissions', url: '/dashboard/submissions' },
  { name: 'keys', url: '/dashboard/keys' },
  { name: 'webhooks', url: '/dashboard/webhooks' },
  { name: 'stats', url: '/dashboard/stats' },
  { name: 'profile', url: '/dashboard/profile' },
] as const

// Where auth.setup.ts stores the signed-in browser state for dashboard specs.
export const STORAGE_STATE = 'e2e-report/.auth/user.json'

// Budgets. Good/needs-work borders follow Core Web Vitals; app-specific flows are
// pragmatic targets we can tighten later. Values in ms except CLS (unitless).
export const BUDGETS = {
  LCP: { good: 2500, poor: 4000 },
  FCP: { good: 1800, poor: 3000 },
  CLS: { good: 0.1, poor: 0.25 },
  TTFB: { good: 800, poor: 1800 },
  // Interaction budgets (wall-clock to the visible result).
  treeRender: { good: 1500, poor: 4000 },
  treeExpand: { good: 800, poor: 2500 },
  searchResults: { good: 1000, poor: 3000 },
  autocomplete: { good: 500, poor: 1500 },
  // MOS (Manchester OWL Syntax) expression query: wall-clock from pressing Enter
  // to the first result row or a terminal message. The front-page surface fans
  // out one request per in-scope ontology, so this is deliberately generous.
  mos: { good: 2000, poor: 6000 },
  // API response p95 across a flow's XHRs.
  apiP95: { good: 500, poor: 1500 },
} as const

function parseOverride(): OntoFixture[] | null {
  const raw = process.env.E2E_ONTOLOGIES
  if (!raw) return null
  return raw.split(',').map((s) => {
    const [slug, n] = s.split(':')
    const entities = Number(n) || 0
    const size = entities < 200 ? 'tiny' : entities < 3000 ? 'small'
      : entities < 12000 ? 'medium' : entities < 40000 ? 'large' : 'giant'
    return { slug, label: slug, entities, size }
  })
}
