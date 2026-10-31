import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useGlobalSearch } from '../hooks/useSearch'
import { useDebounced } from '../hooks/useDebounced'
import { SearchResult, Ontology, api } from '../lib/api'
import SourceBadge from '../components/SourceBadge'
import { MOSQuery } from '../components/MOSQuery'
import { ResultList, TypeBadge } from '../components/ResultList'

// Re-exported for existing importers (Home.mos.test.tsx).
export { normalizeMos, isNamedClassQuery } from '../components/MOSQuery'

const EXAMPLES = ['cell death', 'apoptosis', 'protein binding', 'nucleus', 'membrane']
const ONTOLOGY_EXAMPLES = ['gene', 'disease', 'chemical', 'anatomy', 'protein']

type Mode = 'ontology' | 'search' | 'query'

// Display order + labels for the front-page mode toggle.
const MODES: Mode[] = ['ontology', 'search', 'query']
const MODE_LABELS: Record<Mode, string> = {
  ontology: 'Ontologies',
  search: 'Entities',
  query: 'Query',
}

type EntityTypeFilter = 'class' | 'object_property' | 'data_property' | 'individual' | 'concept'

const TYPE_FILTERS: { value: EntityTypeFilter; label: string }[] = [
  { value: 'class', label: 'Class' },
  { value: 'object_property', label: 'Object Property' },
  { value: 'data_property', label: 'Data Property' },
  { value: 'individual', label: 'Individual' },
  { value: 'concept', label: 'Concept (SKOS)' },
]

function TypeChips({ selected, onChange }: {
  selected: EntityTypeFilter[]
  onChange: (next: EntityTypeFilter[]) => void
}) {
  const isAll = selected.length === 0
  function toggle(v: EntityTypeFilter) {
    if (selected.includes(v)) onChange(selected.filter(s => s !== v))
    else onChange([...selected, v])
  }
  const chipStyle = (active: boolean): React.CSSProperties => ({
    fontSize: 12, padding: '3px 10px', borderRadius: 12,
    background: active ? 'var(--accent)' : 'var(--bg-secondary)',
    border: '1px solid ' + (active ? 'var(--accent)' : 'var(--border)'),
    color: active ? 'var(--on-accent)' : 'var(--text-muted)',
    cursor: 'pointer', fontWeight: active ? 600 : 400,
  })
  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: '0.75rem' }}>
      <button type="button" onClick={() => onChange([])} style={chipStyle(isAll)}>All</button>
      {TYPE_FILTERS.map(f => (
        <button key={f.value} type="button" onClick={() => toggle(f.value)} style={chipStyle(selected.includes(f.value))}>
          {f.label}
        </button>
      ))}
    </div>
  )
}

function StatCard({ label, value, subtitle, to }: { label: string; value: number | string; subtitle?: string; to?: string }) {
  const inner = (
    <>
      <div style={{ fontSize: 26, fontWeight: 700, color: 'var(--text)', fontVariantNumeric: 'tabular-nums' }}>
        {typeof value === 'number' ? value.toLocaleString() : value}
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 4, textTransform: 'uppercase', letterSpacing: 0.5 }}>
        {label}
      </div>
      {subtitle && (
        // No opacity: --text-dim already de-emphasises; dimming further dropped
        // this below 4.5:1 contrast (#192).
        <div style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 3 }}>
          {subtitle}
        </div>
      )}
    </>
  )
  const base: React.CSSProperties = {
    flex: 1, textAlign: 'center',
    background: 'var(--bg-secondary)', border: '1px solid var(--border)',
    borderRadius: 'var(--radius)', padding: '16px 12px',
    display: 'block', textDecoration: 'none',
  }
  return to ? (
    <Link to={to} style={base}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)' }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)' }}
    >
      {inner}
    </Link>
  ) : (
    <div style={base}>{inner}</div>
  )
}

// ── Search tab ────────────────────────────────────────────────────────────────

function OntologySearch() {
  const [query, setQuery] = useState('')
  // Live search over the ontology catalogue, debounced like the entity search.
  // Only fires at >= 2 chars so the idle front page never lists the whole
  // catalogue. Reuses the same `/ontologies?q=` endpoint the catalogue uses.
  const debouncedQuery = useDebounced(query.trim(), 250)
  const activeQuery = debouncedQuery.length >= 2 ? debouncedQuery : ''
  const { data, isFetching } = useQuery({
    queryKey: ['home-ontology-search', activeQuery],
    queryFn: () =>
      api.ontologies.list(0, 50, activeQuery, undefined, undefined, undefined, false, undefined, 'list'),
    enabled: activeQuery.length >= 2,
    staleTime: 30_000,
  })
  const results: Ontology[] = data?.ontologies ?? []
  const total = data?.total ?? results.length

  return (
    <>
      <div style={{ display: 'flex', gap: 8, marginBottom: '0.75rem' }}>
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Search ontologies by name, IRI, or description…"
          autoFocus
          style={{
            flex: 1, padding: '10px 14px', fontSize: 15,
            background: 'var(--bg-secondary)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius)', color: 'var(--text)', outline: 'none',
          }}
          onFocus={e => (e.currentTarget.style.borderColor = 'var(--accent)')}
          onBlur={e => (e.currentTarget.style.borderColor = 'var(--border)')}
        />
        {query && (
          <button
            type="button"
            onClick={() => setQuery('')}
            title="Clear"
            style={{
              padding: '10px 16px', background: 'var(--bg-secondary)', color: 'var(--text-dim)',
              border: '1px solid var(--border)', borderRadius: 'var(--radius)', fontSize: 14, cursor: 'pointer',
            }}
          >
            ✕
          </button>
        )}
      </div>

      {!activeQuery && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>Try:</span>
          {ONTOLOGY_EXAMPLES.map(ex => (
            <button key={ex} onClick={() => setQuery(ex)} style={{
              fontSize: 12, padding: '3px 10px', borderRadius: 12,
              background: 'var(--bg-secondary)', border: '1px solid var(--border)',
              color: 'var(--text-muted)', cursor: 'pointer',
            }}
              onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--accent)')}
              onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--border)')}
            >{ex}</button>
          ))}
        </div>
      )}

      {activeQuery && (
        <div style={{ marginTop: '0.75rem' }}>
          {isFetching && results.length === 0 && (
            <p style={{ color: 'var(--text-dim)', fontSize: 13 }}>Searching…</p>
          )}
          {!isFetching && results.length === 0 && (
            <p style={{ color: 'var(--text-dim)', fontSize: 13 }}>No ontologies match “{activeQuery}”.</p>
          )}
          {results.length > 0 && (
            <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 2 }}>
              {results.map(o => (
                <li key={o.id}>
                  <Link
                    to={`/ontologies/${encodeURIComponent(o.shortname ?? o.id)}`}
                    style={{
                      display: 'flex', alignItems: 'baseline', gap: 8, padding: '8px 12px',
                      borderRadius: 'var(--radius)', textDecoration: 'none', color: 'var(--text)',
                      border: '1px solid transparent',
                    }}
                    onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-secondary)'; e.currentTarget.style.borderColor = 'var(--border)' }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.borderColor = 'transparent' }}
                  >
                    <span style={{ fontWeight: 600 }}>{o.shortname ?? o.title ?? o.iri}</span>
                    {o.title && o.shortname && (
                      <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>{o.title}</span>
                    )}
                    {o.class_count != null && (
                      <span style={{ marginLeft: 'auto', color: 'var(--text-dim)', fontSize: 12, whiteSpace: 'nowrap' }}>
                        {o.class_count.toLocaleString()} classes
                      </span>
                    )}
                  </Link>
                </li>
              ))}
            </ul>
          )}
          {total > results.length && (
            <p style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 8 }}>
              Showing {results.length} of {total.toLocaleString()} — refine your search or{' '}
              <Link to="/ontologies" style={{ color: 'var(--accent)' }}>browse the catalogue</Link>.
            </p>
          )}
        </div>
      )}
    </>
  )
}

function KeywordSearch({ typeFilters, onTypeFiltersChange }: {
  typeFilters: EntityTypeFilter[]
  onTypeFiltersChange: (next: EntityTypeFilter[]) => void
}) {
  const [query, setQuery] = useState('')
  // Live search: fire after the user pauses for 200 ms. Reuses the existing
  // 60s Redis response cache so refinements feel instant.
  const debouncedQuery = useDebounced(query.trim(), 200)
  const activeQuery = debouncedQuery.length >= 2 ? debouncedQuery : ''
  // Keyword results (fast) drive the main list and its loading state. Semantic
  // (vector) search runs as a separate, non-blocking query so a slow embed never
  // holds up the primary results — it fills the "related concepts" section when
  // it arrives.
  const { data, isFetching } = useGlobalSearch(activeQuery, false, typeFilters)
  const { data: semanticData, isFetching: semanticFetching } =
    useGlobalSearch(activeQuery, activeQuery.length >= 2, typeFilters)
  const results = data?.results ?? []
  const semanticResults = semanticData?.semantic_results ?? []

  // Build the term link from the result itself (shortname → clean slug, else the
  // ontology_id, which the term page resolves server-side). This works for every
  // result regardless of catalogue size — the old lookup against the page-capped
  // ontology list left results from ontologies past the cap un-clickable.
  function pathFor(r: SearchResult): string | null {
    if (!r.version_id) return null
    const slug = r.ontology_shortname || r.ontology_id
    if (!slug) return null
    return `/ontologies/${encodeURIComponent(slug)}/${r.version_id}?term=${encodeURIComponent(r.iri)}`
  }

  function ontologyNameFor(r: SearchResult): string | null {
    return r.ontology_shortname || null
  }

  return (
    <>
      <TypeChips selected={typeFilters} onChange={onTypeFiltersChange} />

      <div style={{ display: 'flex', gap: 8, marginBottom: '0.75rem' }}>
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Search classes, properties, individuals…"
          autoFocus
          style={{
            flex: 1, padding: '10px 14px', fontSize: 15,
            background: 'var(--bg-secondary)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius)', color: 'var(--text)', outline: 'none',
          }}
          onFocus={e => (e.currentTarget.style.borderColor = 'var(--accent)')}
          onBlur={e => (e.currentTarget.style.borderColor = 'var(--border)')}
        />
        {query && (
          <button
            type="button"
            onClick={() => setQuery('')}
            title="Clear"
            style={{
              padding: '10px 16px', background: 'var(--bg-secondary)', color: 'var(--text-dim)',
              border: '1px solid var(--border)', borderRadius: 'var(--radius)', fontSize: 14, cursor: 'pointer',
            }}
          >
            ✕
          </button>
        )}
      </div>

      {!activeQuery && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>Try:</span>
          {EXAMPLES.map(ex => (
            <button key={ex} onClick={() => setQuery(ex)} style={{
              fontSize: 12, padding: '3px 10px', borderRadius: 12,
              background: 'var(--bg-secondary)', border: '1px solid var(--border)',
              color: 'var(--text-muted)', cursor: 'pointer',
            }}
              onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--accent)')}
              onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--border)')}
            >{ex}</button>
          ))}
        </div>
      )}

      {activeQuery && isFetching && results.length === 0 && (
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', textAlign: 'center', marginTop: '2rem' }}>
          Searching…
        </p>
      )}
      {activeQuery && !isFetching && results.length === 0 && (
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', textAlign: 'center', marginTop: '2rem' }}>
          No results for "{activeQuery}"
        </p>
      )}
      <ResultList results={results} pathFor={pathFor} ontologyNameFor={ontologyNameFor} />
      {semanticFetching && results.length > 0 && semanticResults.length === 0 && (
        <p style={{ margin: '1rem 0 0', fontSize: 11, color: 'var(--text-dim)', textAlign: 'center' }}>
          finding related concepts…
        </p>
      )}
      {semanticResults.length > 0 && (
        <>
          <div style={{
            margin: '1.25rem 0 0.5rem',
            fontSize: 11, color: 'var(--text-dim)', textTransform: 'uppercase',
            letterSpacing: 0.8, display: 'flex', alignItems: 'center', gap: 8,
          }}>
            <span style={{ flex: 1, borderTop: '1px solid var(--border)' }} />
            Semantically similar
            <span style={{ flex: 1, borderTop: '1px solid var(--border)' }} />
          </div>
          <ul style={{ listStyle: 'none', marginTop: 0 }}>
            {semanticResults.map(r => {
              const path = pathFor(r)
              const alreadyInResults = results.some(p => p.iri === r.iri)
              const semOntName = ontologyNameFor(r)
              const inner = (
                <>
                  <TypeBadge type={r.type} />
                  <span style={{
                    color: alreadyInResults ? 'var(--text-dim)' : 'var(--accent)',
                    fontWeight: 500, flexShrink: 0,
                  }}>{r.label}</span>
                  {r.source && <SourceBadge source={r.source} />}
                  <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{r.short}</span>
                  {semOntName && (
                    <span style={{
                      fontSize: 10, padding: '1px 6px', borderRadius: 3,
                      background: 'var(--bg-secondary)', border: '1px solid var(--border)',
                      color: 'var(--text-dim)', marginLeft: 'auto', flexShrink: 0, fontWeight: 500,
                    }}>{semOntName}</span>
                  )}
                  <span style={{
                    fontSize: 10, padding: '1px 5px', borderRadius: 3,
                    background: 'var(--bg-secondary)', border: '1px solid var(--border)',
                    color: 'var(--text-dim)', flexShrink: 0,
                  }}>{r.score?.toFixed(2)}</span>
                </>
              )
              const sharedStyle: React.CSSProperties = {
                padding: '8px 10px', borderRadius: 'var(--radius-sm)',
                display: 'flex', gap: 10, alignItems: 'baseline',
                borderBottom: '1px solid var(--border)',
                textDecoration: 'none',
                opacity: alreadyInResults ? 0.5 : 1,
              }
              return path ? (
                <li key={r.iri}>
                  <Link to={path} style={sharedStyle}
                    onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
                    onMouseLeave={e => (e.currentTarget.style.background = '')}
                  >{inner}</Link>
                </li>
              ) : (
                <li key={r.iri} style={{ ...sharedStyle, color: 'var(--text-dim)' }}>{inner}</li>
              )
            })}
          </ul>
        </>
      )}
    </>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Home() {
  const [mode, setMode] = useState<Mode>('ontology')
  const [typeFilters, setTypeFilters] = useState<EntityTypeFilter[]>([])

  const { data: publicStats } = useQuery({
    queryKey: ['public-stats'],
    queryFn: () => api.stats.public(),
    staleTime: 300_000,
  })

  return (
    <div style={{ maxWidth: 700, margin: '0 auto', padding: '5rem 1.5rem 3rem' }}>
      <h1 style={{ color: 'var(--text)', fontSize: 28, fontWeight: 700, marginBottom: '0.5rem', textAlign: 'center' }}>
        OntoExplorer
      </h1>
      <p style={{ color: 'var(--text-muted)', textAlign: 'center', marginBottom: '2rem' }}>
        FAIR ontology repository — search and query across all ontologies
      </p>

      {publicStats && (
        <div style={{ display: 'flex', gap: 12, marginBottom: '2rem', flexWrap: 'wrap' }}>
          <StatCard label="Ontologies" value={publicStats.total_ontologies} to="/ontologies" />
          <StatCard label="Classes" value={publicStats.total_classes}
            subtitle={publicStats.unique_classes != null ? `${publicStats.unique_classes.toLocaleString()} unique` : undefined}
            to="/browse?type=class" />
          {publicStats.total_object_properties > 0 && (
            <StatCard label="Object Properties" value={publicStats.total_object_properties}
              subtitle={publicStats.unique_object_properties != null ? `${publicStats.unique_object_properties.toLocaleString()} unique` : undefined}
              to="/browse?type=object_property" />
          )}
          {publicStats.total_data_properties > 0 && (
            <StatCard label="Data Properties" value={publicStats.total_data_properties}
              subtitle={publicStats.unique_data_properties != null ? `${publicStats.unique_data_properties.toLocaleString()} unique` : undefined}
              to="/browse?type=data_property" />
          )}
          {publicStats.total_annotation_properties > 0 && (
            <StatCard label="Annotation Properties" value={publicStats.total_annotation_properties}
              subtitle={publicStats.unique_annotation_properties != null ? `${publicStats.unique_annotation_properties.toLocaleString()} unique` : undefined}
              to="/browse?type=annotation_property" />
          )}
          {publicStats.total_individuals > 0 && (
            <StatCard label="Individuals" value={publicStats.total_individuals}
              subtitle={publicStats.unique_individuals != null ? `${publicStats.unique_individuals.toLocaleString()} unique` : undefined}
              to="/browse?type=individual" />
          )}
          {publicStats.total_axioms > 0 && (
            <StatCard label="Axioms" value={publicStats.total_axioms} to="/browse?mode=query" />
          )}
        </div>
      )}

      {/* Mode toggle */}
      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 12 }}>
      <div style={{ display: 'flex', borderRadius: 'var(--radius)', overflow: 'hidden', border: '1px solid var(--border)' }}>
        {MODES.map(m => (
          <button
            key={m}
            onClick={() => setMode(m)}
            style={{
              padding: '7px 22px', border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: 500,
              background: mode === m ? 'var(--accent)' : 'transparent',
              color: mode === m ? 'var(--on-accent)' : 'var(--text-dim)',
            }}
          >
            {MODE_LABELS[m]}
          </button>
        ))}
      </div>
      </div>

      {mode === 'ontology' && <OntologySearch />}
      {mode === 'search' && <KeywordSearch typeFilters={typeFilters} onTypeFiltersChange={setTypeFilters} />}
      {mode === 'query' && <MOSQuery />}
    </div>
  )
}
