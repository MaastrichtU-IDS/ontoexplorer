import { Link } from 'react-router-dom'
import { useTerm } from '../hooks/useTerm'
import { useClassTreeNodes } from '../hooks/useClassTree'

interface Props {
  ontologyId: string
  versionId: string
  termIri: string
}

function SubclassList({ ontologyId, versionId, parentIri }: { ontologyId: string; versionId: string; parentIri: string }) {
  const { data: childData, isLoading } = useClassTreeNodes(ontologyId, versionId, parentIri)
  const children = childData?.terms ?? []

  if (isLoading) return <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>Loading…</span>
  if (children.length === 0) return <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>No subclasses</span>

  return (
    <ul style={{ listStyle: 'none' }}>
      {children.slice(0, 10).map(c => (
        <li key={c.iri} style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', padding: '2px 0' }}>
          ▸ {c.label ?? c.iri.split(/[#/]/).pop()}
        </li>
      ))}
      {children.length > 10 && (
        <li style={{ color: 'var(--text-dim)', fontSize: 11, padding: '2px 0' }}>
          + {children.length - 10} more…
        </li>
      )}
    </ul>
  )
}

export default function TermPanel({ ontologyId, versionId, termIri }: Props) {
  const { data, isLoading, error } = useTerm(ontologyId, versionId, termIri)

  if (isLoading) return <div style={{ padding: '1rem', color: 'var(--text-dim)' }}>Loading…</div>
  if (error || !data) return <div style={{ padding: '1rem', color: 'var(--text-dim)' }}>Term not found</div>

  const typeColor = data.entityType === 'class' ? 'var(--accent-purple)'
    : data.entityType === 'property' ? 'var(--accent-blue)' : 'var(--text-muted)'
  const shortIri = data.iri.split(/[#/]/).pop() ?? data.iri

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
          {data.superclasses.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', marginBottom: 4 }}>
                Superclasses
              </div>
              {data.superclasses.map(iri => (
                <div key={iri} style={{ color: 'var(--accent)', fontSize: 'var(--font-size-sm)', paddingLeft: 8, marginBottom: 2 }}>
                  {iri.split(/[#/]/).pop()}
                </div>
              ))}
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
          <SubclassList ontologyId={ontologyId} versionId={versionId} parentIri={termIri} />
        </div>
      </div>
    </div>
  )
}
