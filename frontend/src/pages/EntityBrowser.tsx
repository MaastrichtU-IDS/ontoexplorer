import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api, type EntityRow, type Facet } from '../lib/api'
import { useEntities } from '../hooks/useEntities'
import { useRelated } from '../hooks/useRelated'
import { useFacets } from '../hooks/useFacets'
import { useDebounced } from '../hooks/useDebounced'
import { MOSQuery } from '../components/MOSQuery'
import { TypeBadge } from '../components/ResultList'

const TYPES = [
  { key: 'class', label: 'Classes', stat: 'total_classes' },
  { key: 'object_property', label: 'Object properties', stat: 'total_object_properties' },
  { key: 'data_property', label: 'Data properties', stat: 'total_data_properties' },
  { key: 'annotation_property', label: 'Annotation properties', stat: 'total_annotation_properties' },
  { key: 'individual', label: 'Individuals', stat: 'total_individuals' },
] as const

const PAGE_SIZE = 50

const pill = (active: boolean): React.CSSProperties => ({
  padding: '6px 12px', borderRadius: 'var(--radius-sm)', cursor: 'pointer', fontSize: 13,
  border: '1px solid var(--border)',
  background: active ? 'var(--accent)' : 'var(--bg-secondary)',
  color: active ? '#fff' : 'var(--text)',
})

function EntityRowItem({ e, slug, open, onToggle, score }: {
  e: EntityRow; slug: string; open: boolean; onToggle: () => void; score?: number
}) {
  const to = `/ontologies/${encodeURIComponent(slug)}/${e.version_id}?term=${encodeURIComponent(e.iri)}`
  return (
    <li style={{ display: 'flex', gap: 8, padding: '8px 10px', borderBottom: '1px solid var(--border)' }}>
      <button
        type="button" aria-label="Toggle definition" aria-expanded={open} onClick={onToggle}
        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-dim)', width: 20 }}
      >{open ? '▾' : '▸'}</button>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
          <TypeBadge type={e.type} />
          <Link to={to} style={{ color: 'var(--accent)', fontWeight: 500 }}>{e.primary_label || e.short}</Link>
          <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{e.short}</span>
          <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>in {e.ontology_title || e.ontology_id}</span>
        </div>
        {open && (
          <div style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 4 }}>
            {e.definition || 'No definition.'}
          </div>
        )}
      </div>
      {score !== undefined && (
        <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{Math.round(score * 100)}%</span>
      )}
    </li>
  )
}

export default function EntityBrowser() {
  const [params, setParams] = useSearchParams()
  const mode = params.get('mode') === 'query' ? 'query' : 'list'
  const type = TYPES.some(t => t.key === params.get('type')) ? params.get('type')! : 'class'

  const [q, setQ] = useState('')
  const [onts, setOnts] = useState<string[]>([])
  const [ontQ, setOntQ] = useState('')
  const [cursors, setCursors] = useState<string[]>([])
  const [showDefs, setShowDefs] = useState(false)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const dq = useDebounced(q, 200).trim()
  const cursor = cursors.length ? cursors[cursors.length - 1] : undefined

  const { data: stats } = useQuery({
    queryKey: ['public-stats'], queryFn: () => api.stats.public(), staleTime: 300_000,
  })
  const { facets } = useFacets(type)
  const list = useEntities({
    type, q: dq || undefined, ontology: onts, limit: PAGE_SIZE, cursor: dq ? undefined : cursor,
  })
  const related = useRelated({ type, q: dq, ontology: onts }, !!dq)

  const relatedOnly = useMemo(() => {
    const exact = new Set(list.entities.map(e => e.iri))
    return related.entities.filter(e => !exact.has(e.iri))
  }, [list.entities, related.entities])

  const visibleFacets = useMemo(() => {
    const t = ontQ.trim().toLowerCase()
    return facets.filter((f: Facet) => !t || f.short.toLowerCase().includes(t) || f.title.toLowerCase().includes(t))
  }, [facets, ontQ])

  const resetPaging = () => { setCursors([]); setExpanded(new Set()) }
  const update = (k: string, v: string | null) => {
    const next = new URLSearchParams(params)
    if (v === null) next.delete(k); else next.set(k, v)
    setParams(next)
  }
  const switchType = (t: string) => {
    update('type', t); setOnts([]); setOntQ(''); resetPaging()
  }
  const toggleOnt = (id: string) => {
    setOnts(o => (o.includes(id) ? o.filter(x => x !== id) : [...o, id])); setCursors([])
  }
  const rowKey = (e: EntityRow) => `${e.iri}|${e.ontology_id}`
  const toggleRow = (k: string) =>
    setExpanded(s => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n })
  const slugFor = (e: EntityRow) => e.ontology_shortname || e.ontology_id

  const renderRow = (e: EntityRow, score?: number) => (
    <EntityRowItem
      key={rowKey(e)} e={e} slug={slugFor(e)} score={score}
      open={showDefs || expanded.has(rowKey(e))} onToggle={() => toggleRow(rowKey(e))}
    />
  )

  return (
    <div style={{ maxWidth: 1040, margin: '0 auto', padding: '4rem 1.5rem 3rem' }}>
      <h1 style={{ fontSize: 24, marginBottom: 4 }}>Browse entities</h1>
      <p style={{ color: 'var(--text-muted)', marginBottom: 16 }}>
        Every entity behind the repository-wide counts, across all ontologies.
      </p>
      <div role="tablist" aria-label="Browse mode" style={{ display: 'flex', gap: 6, marginBottom: 16 }}>
        <button role="tab" aria-selected={mode === 'list'} style={pill(mode === 'list')}
          onClick={() => update('mode', null)}>List</button>
        <button role="tab" aria-selected={mode === 'query'} style={pill(mode === 'query')}
          onClick={() => update('mode', 'query')}>Structured query</button>
      </div>

      {mode === 'query' ? (
        <section>
          <MOSQuery />
          <p style={{ marginTop: 12, fontSize: 13 }}>
            or <Link to="/sparql" style={{ color: 'var(--accent)' }}>browse axioms in SPARQL →</Link> for raw triples
          </p>
        </section>
      ) : (
        <section>
          <div role="tablist" aria-label="Entity type" style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
            {TYPES.map(t => {
              const n = (stats as Record<string, number> | undefined)?.[t.stat]
              return (
                <button key={t.key} role="tab" aria-selected={t.key === type}
                  style={pill(t.key === type)} onClick={() => switchType(t.key)}>
                  {t.label}{n != null && <> <span style={{ opacity: 0.8 }}>{n.toLocaleString()}</span></>}
                </button>
              )
            })}
          </div>

          <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
            <input
              aria-label="Search" type="text" value={q} autoComplete="off" placeholder="Search entities…"
              onChange={e => { setQ(e.target.value); setCursors([]) }}
              style={{ flex: 1, minWidth: 200, padding: '8px 10px' }}
            />
            <button type="button" aria-pressed={showDefs} style={pill(showDefs)}
              onClick={() => setShowDefs(s => !s)}>
              {showDefs ? 'Hide definitions' : 'Show definitions'}
            </button>
            {list.data && (
              <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
                {dq ? `${list.entities.length} matches` : `≈ ${list.data.approx_total?.toLocaleString?.() ?? ''}`}
              </span>
            )}
          </div>

          <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start', flexWrap: 'wrap' }}>
            <aside aria-label="Filter by ontology" style={{ width: 220, flexShrink: 0 }}>
              <h2 style={{ fontSize: 13, marginBottom: 6 }}>Ontology</h2>
              <input
                aria-label="Search ontologies" type="text" value={ontQ} placeholder="Search ontologies…"
                onChange={e => setOntQ(e.target.value)} style={{ width: '100%', padding: '6px 8px', marginBottom: 6 }}
              />
              <div style={{ maxHeight: 360, overflowY: 'auto' }}>
                {visibleFacets.map((f: Facet) => (
                  <label key={f.ontology_id} title={f.title}
                    style={{ display: 'flex', gap: 6, fontSize: 12, padding: '2px 0', alignItems: 'center' }}>
                    <input type="checkbox" checked={onts.includes(f.ontology_id)}
                      onChange={() => toggleOnt(f.ontology_id)} />
                    <span style={{ flex: 1 }}>{f.short}</span>
                    <span style={{ color: 'var(--text-dim)' }}>{f.count.toLocaleString()}</span>
                  </label>
                ))}
              </div>
              {onts.length > 0 && (
                <button type="button" onClick={() => { setOnts([]); setCursors([]) }}
                  style={{ marginTop: 6, fontSize: 12 }}>Clear filter</button>
              )}
            </aside>

            <div style={{ flex: 1, minWidth: 0 }}>
              {list.isLoading && <p style={{ color: 'var(--text-dim)' }}>Loading…</p>}
              {!list.isLoading && list.entities.length === 0 && (
                <p style={{ color: 'var(--text-dim)' }}>No entities found.</p>
              )}
              <ul style={{ listStyle: 'none', padding: 0 }}>{list.entities.map(e => renderRow(e))}</ul>

              {dq && !related.unavailable && relatedOnly.length > 0 && (
                <>
                  <h3 style={{ fontSize: 12, textTransform: 'uppercase', letterSpacing: 0.5, margin: '16px 0 4px', color: 'var(--text-dim)' }}>
                    Related by meaning
                  </h3>
                  <ul style={{ listStyle: 'none', padding: 0 }}>
                    {relatedOnly.map(e => renderRow(e, e.score))}
                  </ul>
                </>
              )}

              {!dq && (
                <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                  <button type="button" disabled={cursors.length === 0}
                    onClick={() => { setCursors(c => c.slice(0, -1)); setExpanded(new Set()) }}>← Previous</button>
                  <button type="button" disabled={!list.data?.next}
                    onClick={() => { const n = list.data?.next; if (n) { setCursors(c => [...c, n]); setExpanded(new Set()) } }}>
                    Next →
                  </button>
                </div>
              )}
            </div>
          </div>
        </section>
      )}
    </div>
  )
}
