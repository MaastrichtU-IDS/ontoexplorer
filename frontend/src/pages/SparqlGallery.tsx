import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, SavedQuery } from '../lib/api'

const LIMIT = 20

function relativeDate(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days < 7) return `${days}d ago`
  return new Date(iso).toLocaleDateString()
}

export default function SparqlGallery() {
  const navigate = useNavigate()
  const [queries, setQueries] = useState<SavedQuery[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [pageOffset, setPageOffset] = useState(0)
  const [searchInput, setSearchInput] = useState('')
  const [searchQ, setSearchQ] = useState('')
  const [ontologyFilter, setOntologyFilter] = useState('')
  const [authorFilter, setAuthorFilter] = useState<{ id: string; name: string } | null>(null)
  const [ontologyOptions, setOntologyOptions] = useState<string[]>([])
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    api.ontologies.list(0, 200)
      .then(r => setOntologyOptions(r.ontologies.map(o => o.shortname).filter(Boolean) as string[]))
      .catch(() => {})
  }, [])

  const fetchQueries = useCallback(async (
    q: string,
    ontology: string,
    userId: string | undefined,
    newOffset: number,
    append: boolean,
  ) => {
    setLoading(true)
    try {
      const r = await api.savedQueries.listPublic({
        q: q || undefined,
        ontology: ontology || undefined,
        user_id: userId,
        limit: LIMIT,
        offset: newOffset,
      })
      setQueries(prev => append ? [...prev, ...r.queries] : r.queries)
      setTotal(r.total)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    setPageOffset(0)
    fetchQueries(searchQ, ontologyFilter, authorFilter?.id, 0, false)
  }, [searchQ, ontologyFilter, authorFilter, fetchQueries])

  function handleSearchChange(e: React.ChangeEvent<HTMLInputElement>) {
    const v = e.target.value
    setSearchInput(v)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => setSearchQ(v), 300)
  }

  function loadMore() {
    const next = pageOffset + LIMIT
    setPageOffset(next)
    fetchQueries(searchQ, ontologyFilter, authorFilter?.id, next, true)
  }

  // Build unique author list from current result set
  const authorMap = new Map<string, string>()
  queries.forEach(q => {
    if (q.user_display_name) authorMap.set(q.user_id, q.user_display_name)
  })
  const authors = Array.from(authorMap.entries()).map(([id, name]) => ({ id, name }))

  return (
    <div style={{ minHeight: 'calc(100vh - var(--nav-height))', background: 'var(--bg)' }}>
      {/* Header */}
      <div style={{ padding: '1rem 1.5rem', borderBottom: '1px solid var(--border)', background: 'var(--bg-secondary)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
          <h1 style={{ fontSize: '1.3rem', fontWeight: 700, color: 'var(--text)', margin: 0 }}>Query Gallery</h1>
          <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
            {total} public {total === 1 ? 'query' : 'queries'}
          </span>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
          <input
            type="text"
            placeholder="🔍 Search by name, description, or tag…"
            value={searchInput}
            onChange={handleSearchChange}
            style={{ flex: 1, minWidth: 200, background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 4, padding: '0.4rem 0.75rem', color: 'var(--text)', fontSize: 'var(--font-size-sm)', outline: 'none' }}
          />
          <select
            value={ontologyFilter}
            onChange={e => setOntologyFilter(e.target.value)}
            style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 4, padding: '0.4rem 0.75rem', color: ontologyFilter ? 'var(--text)' : 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}
          >
            <option value="">Ontology ▾</option>
            {ontologyOptions.map(o => <option key={o} value={o}>{o}</option>)}
          </select>
          <select
            value={authorFilter?.id ?? ''}
            onChange={e => {
              const found = authors.find(a => a.id === e.target.value) ?? null
              setAuthorFilter(found)
            }}
            style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 4, padding: '0.4rem 0.75rem', color: authorFilter ? 'var(--text)' : 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}
          >
            <option value="">Author ▾</option>
            {authors.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </div>
      </div>

      {/* Grid */}
      <div style={{ padding: '1rem 1.5rem', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: '0.75rem' }}>
        {queries.map(q => (
          <div
            key={q.id}
            style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, padding: '0.75rem 1rem', display: 'flex', flexDirection: 'column', gap: '0.4rem' }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <span style={{ color: 'var(--text)', fontWeight: 600, fontSize: 'var(--font-size-sm)', flex: 1, marginRight: '0.5rem' }}>
                {q.name}
              </span>
              <span
                onClick={() => navigate(`/sparql?q=${q.id}`)}
                style={{ color: 'var(--accent-blue)', fontSize: '0.7rem', cursor: 'pointer', flexShrink: 0 }}
              >Open ↗</span>
            </div>
            {q.description && (
              <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                {q.description}
              </div>
            )}
            {q.tags.length > 0 && (
              <div style={{ display: 'flex', gap: '0.25rem', flexWrap: 'wrap' }}>
                {q.tags.map(t => (
                  <span key={t} style={{ background: 'rgba(103,232,249,0.08)', border: '1px solid rgba(103,232,249,0.2)', color: 'var(--accent-blue)', borderRadius: 3, padding: '1px 5px', fontSize: '0.65rem' }}>
                    {t}
                  </span>
                ))}
              </div>
            )}
            <div style={{ color: 'var(--text-dim)', fontSize: '0.65rem' }}>
              {q.user_display_name ?? 'Unknown'} · {relativeDate(q.updated_at)}
            </div>
          </div>
        ))}
        {queries.length === 0 && !loading && (
          <div style={{ gridColumn: '1 / -1', textAlign: 'center', color: 'var(--text-dim)', padding: '3rem 0' }}>
            No public queries found.
          </div>
        )}
      </div>

      {queries.length < total && (
        <div style={{ padding: '1rem 1.5rem', textAlign: 'center' }}>
          <button
            onClick={loadMore}
            disabled={loading}
            style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-muted)', borderRadius: 4, padding: '0.5rem 1.5rem', fontSize: 'var(--font-size-sm)', cursor: 'pointer' }}
          >{loading ? 'Loading…' : 'Load more'}</button>
        </div>
      )}
    </div>
  )
}
