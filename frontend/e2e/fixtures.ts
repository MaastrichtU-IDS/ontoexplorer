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
