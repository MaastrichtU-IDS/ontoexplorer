import { Link, useSearchParams } from 'react-router-dom'
import { useState } from 'react'
import { useEntities } from '../hooks/useEntities'
import { useOntologies } from '../hooks/useOntologies'
import { EntityRow, slugFromIri } from '../lib/api'
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

function EntityListRows({ rows }: { rows: EntityRow[] }) {
  const { ontologies } = useOntologies()
  function pathFor(r: EntityRow): string | null {
    const ont = ontologies.find(o => o.id === r.ontology_id)
    if (!ont || !r.version_id) return null
    return `/ontologies/${slugFromIri(ont.iri)}/${r.version_id}?term=${encodeURIComponent(r.iri)}`
  }
  function ontName(r: EntityRow): string | null {
    const ont = ontologies.find(o => o.id === r.ontology_id)
    if (!ont) return null
    if (ont.shortname) return ont.shortname
    const last = ont.iri.replace(/[/#]+$/, '').split(/[/#]/).pop() ?? ont.iri
    return last.replace(/\.(owl|ttl|rdf|obo|json|xml|nt)$/i, '')
  }
  return (
    <ul style={{ listStyle: 'none', marginTop: '0.5rem' }}>
      {rows.map(r => {
        const path = pathFor(r)
        const name = ontName(r)
        const inner = (
          <>
            <span style={{
              fontSize: 9, padding: '1px 5px', borderRadius: 3,
              background: 'var(--bg-secondary)', border: '1px solid var(--border)',
              color: 'var(--text-dim)', flexShrink: 0, fontWeight: 600, letterSpacing: 0.3,
            }}>{TYPE_BADGE[r.type] ?? r.type}</span>
            <span style={{ color: 'var(--accent)', fontWeight: 500 }}>{r.label}</span>
            <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{r.short}</span>
            {name && (
              <span style={{
                fontSize: 10, padding: '1px 6px', borderRadius: 3,
                background: 'var(--bg-secondary)', border: '1px solid var(--border)',
                color: 'var(--text-dim)', marginLeft: 'auto', flexShrink: 0, fontWeight: 500,
              }}>{name}</span>
            )}
          </>
        )
        const style: React.CSSProperties = {
          padding: '8px 10px', borderRadius: 'var(--radius-sm)',
          display: 'flex', gap: 10, alignItems: 'baseline',
          borderBottom: '1px solid var(--border)', textDecoration: 'none',
        }
        return path ? (
          <li key={`${r.version_id}:${r.iri}`}>
            <Link to={path} style={style}
              onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
              onMouseLeave={e => (e.currentTarget.style.background = '')}
            >{inner}</Link>
          </li>
        ) : (
          <li key={`${r.version_id}:${r.iri}`} style={{ ...style, color: 'var(--text-dim)' }}>{inner}</li>
        )
      })}
    </ul>
  )
}

function ListMode({ type, onType }: { type: EntityType; onType: (t: EntityType) => void }) {
  // Cursor stack: `stack` holds the cursors for previous pages; `cursor` is the
  // current page's start (null = first page). Keyset paging - no offset.
  const [cursor, setCursor] = useState<string | null>(null)
  const [stack, setStack] = useState<(string | null)[]>([])
  const { data, isFetching, isError } = useEntities({ type, limit: PAGE_SIZE, cursor })
  const rows = data?.entities ?? []
  const next = data?.next ?? null
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
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: '1rem' }}>
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

      {isError && (
        <p style={{ color: 'var(--error)', textAlign: 'center', marginTop: '2rem' }}>
          Could not load {typeLabel}. Try again.
        </p>
      )}
      {!isError && approxTotal === 0 && rows.length === 0 && !isFetching && (
        <p style={{ color: 'var(--text-dim)', textAlign: 'center', marginTop: '2rem' }}>
          No {typeLabel} in the repository yet
        </p>
      )}
      {!isError && (rows.length > 0 || approxTotal > 0) && (
        <>
          <div style={{ color: 'var(--text-dim)', fontSize: 11, marginBottom: 4 }}>
            ~{approxTotal.toLocaleString()} {typeLabel}
          </div>
          <EntityListRows rows={rows} />
          <div style={{ display: 'flex', gap: 8, marginTop: 8, justifyContent: 'center' }}>
            <button type="button" onClick={goPrev} disabled={stack.length === 0} style={btn(stack.length === 0)}>
              ← Previous
            </button>
            <button type="button" onClick={goNext} disabled={!next} style={btn(!next)}>
              Next →
            </button>
          </div>
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
