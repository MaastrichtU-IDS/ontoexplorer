import { Link } from 'react-router-dom'
import { useTerm } from '../hooks/useTerm'
import { ClassRef } from '../lib/api'

interface Props {
  ontologyId: string
  versionId: string
  termIri: string
}

function ClassItem({ c, oid, vid }: { c: ClassRef; oid: string; vid: string }) {
  return (
    <div style={{ color: 'var(--accent)', fontSize: 'var(--font-size-sm)', paddingLeft: 8, marginBottom: 2 }}>
      <Link
        to={`/browse/${oid}/${vid}?term=${encodeURIComponent(c.iri)}`}
        style={{ color: 'var(--accent)', textDecoration: 'none' }}
      >
        {c.label}
      </Link>
    </div>
  )
}

function HierGroup({ label, items, oid, vid, badge }: {
  label: string; items: ClassRef[]; oid: string; vid: string; badge?: string
}) {
  if (items.length === 0) return null
  return (
    <div style={{ marginBottom: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 3 }}>
        <span style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase' }}>{label}</span>
        {badge && (
          <span style={{
            fontSize: 9, background: 'var(--bg)', color: 'var(--text-dim)',
            borderRadius: 2, padding: '1px 4px',
          }}>{badge}</span>
        )}
      </div>
      {items.map(c => <ClassItem key={c.iri} c={c} oid={oid} vid={vid} />)}
    </div>
  )
}

export default function TermPanel({ ontologyId, versionId, termIri }: Props) {
  const { data, isLoading, error } = useTerm(ontologyId, versionId, termIri)

  if (isLoading) return <div style={{ padding: '1rem', color: 'var(--text-dim)' }}>Loading…</div>
  if (error || !data) return <div style={{ padding: '1rem', color: 'var(--text-dim)' }}>Term not found</div>

  const typeColor = data.entityType === 'class' ? 'var(--accent-purple)'
    : data.entityType === 'property' ? 'var(--accent-blue)' : 'var(--text-muted)'
  const shortIri = data.iri.split(/[#/]/).pop() ?? data.iri

  const hasSuperclasses = data.superclasses.asserted.length > 0 || data.superclasses.inferred.length > 0
  const hasSubclasses   = data.subclasses.asserted.length > 0   || data.subclasses.inferred.length > 0

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* Header */}
      <div style={{
        padding: '10px 12px', borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
      }}>
        <span style={{ fontWeight: 600, color: 'var(--accent)', flex: 1 }}>{data.label}</span>
        <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>{shortIri}</span>
        <span style={{
          fontSize: 10, background: 'var(--bg)', color: typeColor,
          borderRadius: 3, padding: '1px 5px', textTransform: 'uppercase',
        }}>{data.entityType}</span>
        <Link
          to={`/browse/${ontologyId}/${versionId}/term/${encodeURIComponent(data.iri)}`}
          style={{ color: 'var(--text-dim)', fontSize: 11, flexShrink: 0 }}
        >
          Open full page ↗
        </Link>
      </div>

      {/* Split body */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* Left: definition + superclasses + synonyms */}
        <div style={{ flex: 1, padding: '10px 12px', overflow: 'auto', borderRight: '1px solid var(--border)' }}>
          {data.definition && (
            <p style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', marginBottom: 10, lineHeight: 1.5 }}>
              {data.definition}
            </p>
          )}
          {hasSuperclasses && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', marginBottom: 4 }}>
                Superclasses
              </div>
              <HierGroup label="asserted" items={data.superclasses.asserted} oid={ontologyId} vid={versionId} />
              <HierGroup label="inferred" items={data.superclasses.inferred} oid={ontologyId} vid={versionId} badge="ELK" />
            </div>
          )}
          {(data.synonyms.exact.length > 0 || data.synonyms.related.length > 0) && (
            <div>
              <div style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', marginBottom: 4 }}>
                Synonyms
              </div>
              <div style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)' }}>
                {[...data.synonyms.exact, ...data.synonyms.related].join(' · ')}
              </div>
            </div>
          )}
        </div>

        {/* Right: subclasses */}
        <div style={{ flex: 1, padding: '10px 12px', overflow: 'auto' }}>
          <div style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', marginBottom: 6 }}>
            Subclasses
          </div>
          {hasSubclasses ? (
            <>
              <HierGroup label="asserted" items={data.subclasses.asserted} oid={ontologyId} vid={versionId} />
              <HierGroup label="inferred" items={data.subclasses.inferred} oid={ontologyId} vid={versionId} badge="ELK" />
            </>
          ) : (
            <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>No subclasses</span>
          )}
        </div>
      </div>
    </div>
  )
}
