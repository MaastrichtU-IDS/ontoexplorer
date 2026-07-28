import { Link, useSearchParams } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { useEntities } from '../hooks/useEntities'
import { useOntologies } from '../hooks/useOntologies'
import { useDebounced } from '../hooks/useDebounced'
import { EntityRow, EntityOccurrence, Ontology, slugFromIri } from '../lib/api'
import { MOSQuery } from './Home'

const PAGE_SIZE = 50

type EntityType = 'class' | 'object_property' | 'data_property' | 'annotation_property' | 'individual'

const TYPE_TABS: { value: EntityType; label: string }[] = [
  { value: 'class', label: 'Classes' },
  { value: 'object_property', label: 'Object Properties' },
  { value: 'data_property', label: 'Data Properties' },
  { value: 'annotation_property', label: 'Annotation Properties' },
  { value: 'individual', label: 'Individuals' },
]

const TYPE_BADGE: Record<string, string> = {
  class: 'CLASS', object_property: 'OP', data_property: 'DP',
  annotation_property: 'AP', individual: 'IND',
}

function ontDisplayName(ont: Ontology): string {
  if (ont.shortname) return ont.shortname
  const last = ont.iri.replace(/[/#]+$/, '').split(/[/#]/).pop() ?? ont.iri
  return last.replace(/\.(owl|ttl|rdf|obo|json|xml|nt)$/i, '')
}

const badgeBase: React.CSSProperties = {
  fontSize: 10, padding: '1px 6px', borderRadius: 3,
  background: 'var(--bg-secondary)', border: '1px solid var(--border)',
  fontWeight: 500, flexShrink: 0, textDecoration: 'none',
}

function EntityListRows({ rows }: { rows: EntityRow[] }) {
  const { ontologies } = useOntologies()
  const ontById = (id: string) => ontologies.find(o => o.id === id)
  function termPath(occ: EntityOccurrence, iri: string): string | null {
    const ont = ontById(occ.ontology_id)
    if (!ont || !occ.version_id) return null
    return `/ontologies/${slugFromIri(ont.iri)}/${occ.version_id}?term=${encodeURIComponent(iri)}`
  }
  function occName(occ: EntityOccurrence): string {
    const ont = ontById(occ.ontology_id)
    return ont ? ontDisplayName(ont) : occ.ontology_id.slice(0, 8)
  }
  // The defining ontology owns the term's namespace: its IRI is a namespace
  // prefix of the term IRI (e.g. sulo owns https://w3id.org/sulo/hasValue).
  // Everything else that has the term merely reuses it.
  function defines(occ: EntityOccurrence, termIri: string): boolean {
    const ont = ontById(occ.ontology_id)
    if (!ont || !termIri.startsWith(ont.iri)) return false
    if (/[/#]$/.test(ont.iri)) return true
    const next = termIri.charAt(ont.iri.length)
    return next === '' || next === '/' || next === '#'
  }
  return (
    <ul style={{ listStyle: 'none', marginTop: '0.5rem' }}>
      {rows.map(r => {
        const single = r.ontologies.length === 1
        const soloPath = single ? termPath(r.ontologies[0], r.iri) : null
        return (
          <li key={`${r.iri}:${r.ontologies.map(o => o.version_id).join(',')}`}
            style={{
              padding: '8px 10px', borderRadius: 'var(--radius-sm)',
              display: 'flex', gap: 10, alignItems: 'baseline',
              borderBottom: '1px solid var(--border)',
            }}
            onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
            onMouseLeave={e => (e.currentTarget.style.background = '')}
          >
            <span style={{
              fontSize: 9, padding: '1px 5px', borderRadius: 3,
              background: 'var(--bg-secondary)', border: '1px solid var(--border)',
              color: 'var(--text-dim)', flexShrink: 0, fontWeight: 600, letterSpacing: 0.3,
            }}>{TYPE_BADGE[r.type] ?? r.type}</span>
            {soloPath
              ? <Link to={soloPath} style={{ color: 'var(--accent)', fontWeight: 500, textDecoration: 'none' }}>{r.label}</Link>
              : <span style={{ color: 'var(--text)', fontWeight: 500 }}>{r.label}</span>}
            <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{r.short}</span>
            {/* One clickable badge per ontology whose default version has this term.
                When a term is shared across ontologies, the defining ontology
                (namespace owner) is filled/accented and sorted first, reusers are
                outlined. For a single ontology there is nothing to contrast, so the
                badge stays neutral (avoids mislabeling a native term as "reuse"
                when the owner can't be proven, e.g. OBO PURLs). */}
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 4, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              {[...r.ontologies]
                .sort((a, b) => Number(defines(b, r.iri)) - Number(defines(a, r.iri)))
                .map(occ => {
                  const p = termPath(occ, r.iri)
                  const nm = occName(occ)
                  const multi = r.ontologies.length > 1
                  const isDef = multi && defines(occ, r.iri)
                  const style: React.CSSProperties = isDef
                    ? { ...badgeBase, background: 'var(--accent)', border: '1px solid var(--accent)', color: 'var(--on-accent)', fontWeight: 600 }
                    : { ...badgeBase, color: p ? 'var(--accent)' : 'var(--text-dim)' }
                  const title = !multi ? `Open in ${nm}`
                    : isDef ? `Defines this term — open in ${nm}`
                    : `Reuses this term — open in ${nm}`
                  return p
                    ? <Link key={occ.version_id} to={p} title={title} style={style}>{nm}</Link>
                    : <span key={occ.version_id} title={title} style={style}>{nm}</span>
                })}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

function ListMode({ type, onType }: { type: EntityType; onType: (t: EntityType) => void }) {
  // Keyset paging: `stack` holds prior pages' cursors; `cursor` is the current
  // page's start (null = first page). No offset.
  const [cursor, setCursor] = useState<string | null>(null)
  const [stack, setStack] = useState<(string | null)[]>([])
  const [collapse, setCollapse] = useState(false)
  const [queryText, setQueryText] = useState('')
  const q = useDebounced(queryText.trim(), 250)
  const searching = q.length >= 2

  // Changing the search text or the collapse toggle changes the result set, so
  // reset pagination to the first page.
  useEffect(() => { setCursor(null); setStack([]) }, [q, collapse])

  const { data, isFetching, isError } = useEntities({
    type, limit: PAGE_SIZE,
    // While searching, the endpoint returns a single ranked page (no cursor /
    // collapse); otherwise it's the keyset listing.
    cursor: searching ? null : cursor,
    q: searching ? q : undefined,
    collapse: searching ? false : collapse,
  })
  const rows = data?.entities ?? []
  const next = searching ? null : (data?.next ?? null)
  const approxTotal = data?.approx_total ?? 0
  const typeLabel = TYPE_TABS.find(t => t.value === type)?.label.toLowerCase() ?? 'entities'

  function switchType(t: EntityType) {
    setStack([]); setCursor(null); onType(t)
  }
  function goNext() {
    if (!next) return
    setStack(s => [...s, cursor]); setCursor(next)
  }
  function goPrev() {
    setStack(s => {
      if (s.length === 0) return s
      const copy = [...s]; const prev = copy.pop() ?? null; setCursor(prev); return copy
    })
  }

  const btn = (disabled: boolean): React.CSSProperties => ({
    background: 'none', border: '1px solid var(--border)', borderRadius: 4,
    color: disabled ? 'var(--text-dim)' : 'var(--text)', fontSize: 12,
    padding: '4px 12px', cursor: disabled ? 'default' : 'pointer', opacity: disabled ? 0.4 : 1,
  })

  return (
    <>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: '0.75rem' }}>
        {TYPE_TABS.map(t => (
          <button key={t.value} type="button" onClick={() => switchType(t.value)} style={{
            fontSize: 12, padding: '4px 12px', borderRadius: 12,
            background: type === t.value ? 'var(--accent)' : 'var(--bg-secondary)',
            border: '1px solid ' + (type === t.value ? 'var(--accent)' : 'var(--border)'),
            color: type === t.value ? 'var(--on-accent)' : 'var(--text-muted)',
            cursor: 'pointer', fontWeight: type === t.value ? 600 : 400,
          }}>{t.label}</button>
        ))}
      </div>

      {/* Search + collapse controls */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: '0.75rem' }}>
        <input
          value={queryText}
          onChange={e => setQueryText(e.target.value)}
          placeholder={`Search ${typeLabel}… (exact + fuzzy)`}
          aria-label="Search entities"
          style={{
            flex: 1, padding: '8px 12px', fontSize: 14,
            background: 'var(--bg-secondary)', border: '1px solid var(--border)',
            borderRadius: 'var(--radius)', color: 'var(--text)', outline: 'none',
          }}
          onFocus={e => (e.currentTarget.style.borderColor = 'var(--accent)')}
          onBlur={e => (e.currentTarget.style.borderColor = 'var(--border)')}
        />
        {queryText && (
          <button type="button" onClick={() => setQueryText('')} title="Clear" style={btn(false)}>✕</button>
        )}
        <label title="Show each term once, aggregating the ontologies that use it"
          style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12,
            color: searching ? 'var(--text-dim)' : 'var(--text-muted)',
            cursor: searching ? 'not-allowed' : 'pointer', flexShrink: 0 }}>
          <input type="checkbox" checked={collapse} disabled={searching}
            onChange={e => setCollapse(e.target.checked)}
            style={{ cursor: searching ? 'not-allowed' : 'pointer', accentColor: 'var(--accent)' }} />
          Collapse duplicates
        </label>
      </div>

      {isError && (
        <p style={{ color: 'var(--error)', textAlign: 'center', marginTop: '2rem' }}>
          Could not load {typeLabel}. Try again.
        </p>
      )}
      {!isError && isFetching && !data && (
        <p style={{ color: 'var(--text-dim)', textAlign: 'center', marginTop: '2rem' }}>Loading…</p>
      )}
      {!isError && !isFetching && rows.length === 0 && (
        <p style={{ color: 'var(--text-dim)', textAlign: 'center', marginTop: '2rem' }}>
          {searching ? `No ${typeLabel} matching "${q}"` : `No ${typeLabel} in the repository yet`}
        </p>
      )}
      {!isError && rows.length > 0 && (
        <>
          <div style={{ color: 'var(--text-dim)', fontSize: 11, marginBottom: 4 }}>
            {searching
              ? `${rows.length} result${rows.length === 1 ? '' : 's'} for "${q}"`
              : `~${approxTotal.toLocaleString()} ${typeLabel}${collapse ? ' (deduplicated)' : ''}`}
          </div>
          <EntityListRows rows={rows} />
          {!searching && (
            <div style={{ display: 'flex', gap: 8, marginTop: 8, justifyContent: 'center' }}>
              <button type="button" onClick={goPrev} disabled={stack.length === 0 || isFetching} style={btn(stack.length === 0 || isFetching)}>
                ← Previous
              </button>
              <button type="button" onClick={goNext} disabled={!next || isFetching} style={btn(!next || isFetching)}>
                Next →
              </button>
            </div>
          )}
        </>
      )}
    </>
  )
}

export default function Browse() {
  const [params, setParams] = useSearchParams()
  const mode = params.get('mode') === 'query' ? 'query' : 'list'
  const type = (params.get('type') as EntityType) || 'class'
  const [relation, setRelation] = useState<'subclasses' | 'superclasses' | 'equivalent'>('subclasses')

  function setMode(next: 'list' | 'query') {
    const p = new URLSearchParams(params)
    if (next === 'query') { p.set('mode', 'query') } else { p.delete('mode') }
    setParams(p, { replace: true })
  }
  function setType(next: EntityType) {
    const p = new URLSearchParams(params)
    p.set('type', next)
    setParams(p, { replace: true })
  }

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: '3rem 1.5rem' }}>
      <h1 style={{ color: 'var(--text)', fontSize: 22, fontWeight: 700, marginBottom: '1rem', textAlign: 'center' }}>
        Browse the repository
      </h1>

      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>
        <div style={{ display: 'flex', borderRadius: 'var(--radius)', overflow: 'hidden', border: '1px solid var(--border)' }}>
          {(['list', 'query'] as const).map(m => (
            <button key={m} onClick={() => setMode(m)} style={{
              padding: '7px 22px', border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: 500,
              background: mode === m ? 'var(--accent)' : 'transparent',
              color: mode === m ? 'var(--on-accent)' : 'var(--text-dim)',
            }}>{m === 'list' ? 'List' : 'Structured Query'}</button>
          ))}
        </div>
      </div>

      {mode === 'list' ? (
        // key=type remounts ListMode on type change so its cursor stack resets cleanly
        <ListMode key={type} type={type} onType={setType} />
      ) : (
        <>
          <p style={{ color: 'var(--text-dim)', fontSize: 12, textAlign: 'center', marginBottom: 12 }}>
            Probe the logical content with a Manchester expression, or{' '}
            <Link to="/sparql/gallery" style={{ color: 'var(--accent)' }}>browse axioms in SPARQL →</Link>
          </p>
          <MOSQuery relation={relation} onRelationChange={setRelation} />
        </>
      )}
    </div>
  )
}
