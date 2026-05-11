import { useParams } from 'react-router-dom'
import { useTerm } from '../hooks/useTerm'
import { useClassTreeNodes } from '../hooks/useClassTree'

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ marginBottom: '1.5rem' }}>
      <h2 style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 1, marginBottom: '0.5rem' }}>
        {title}
      </h2>
      {children}
    </section>
  )
}

export default function TermPage() {
  const { oid, vid, '*': termIriEncoded } = useParams()
  const termIri = termIriEncoded ? decodeURIComponent(termIriEncoded) : null
  const { data, isLoading, error } = useTerm(oid ?? null, vid ?? null, termIri)
  const { data: subclassData } = useClassTreeNodes(oid ?? null, vid ?? null, termIri)

  if (isLoading) return <div style={{ padding: '2rem', color: 'var(--text-dim)' }}>Loading…</div>
  if (error || !data) return <div style={{ padding: '2rem', color: 'var(--text-dim)' }}>Term not found</div>

  const typeColor = data.entityType === 'class' ? 'var(--accent-purple)'
    : data.entityType === 'property' ? 'var(--accent-blue)' : 'var(--text-muted)'

  const subclasses = subclassData?.terms ?? []

  return (
    <div style={{ maxWidth: 800, margin: '0 auto', padding: '2rem 1.5rem' }}>
      {/* Breadcrumb */}
      <div style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', marginBottom: '1.5rem' }}>
        <a href="/browse">Browse</a>
        {' → '}
        <a href={`/browse/${oid}/${vid}`}>{oid}</a>
        {' → '}
        <span style={{ color: 'var(--text-muted)' }}>{data.label}</span>
      </div>

      {/* Header */}
      <Section title="Term">
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
          <h1 style={{ color: 'var(--accent)', fontSize: 22, fontWeight: 700 }}>{data.label}</h1>
          <span style={{
            fontSize: 11, background: 'var(--bg-secondary)', color: typeColor,
            borderRadius: 3, padding: '2px 8px',
          }}>{data.entityType}</span>
        </div>
        <div
          style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', cursor: 'pointer', wordBreak: 'break-all' }}
          onClick={() => navigator.clipboard.writeText(data.iri)}
          title="Click to copy IRI"
        >
          {data.iri}
        </div>
      </Section>

      {/* Definition */}
      {data.definition && (
        <Section title="Definition">
          <p style={{ color: 'var(--text-muted)', lineHeight: 1.6 }}>{data.definition}</p>
        </Section>
      )}

      {/* Synonyms */}
      {Object.entries(data.synonyms).some(([, v]) => v.length > 0) && (
        <Section title="Synonyms">
          {(['exact', 'related', 'broad', 'narrow'] as const).map(type => (
            data.synonyms[type].length > 0 && (
              <div key={type} style={{ marginBottom: 6 }}>
                <span style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'capitalize', marginRight: 8 }}>{type}:</span>
                {data.synonyms[type].map((s, i) => (
                  <span key={i} style={{ color: 'var(--text-muted)', marginRight: 8 }}>{s}</span>
                ))}
              </div>
            )
          ))}
        </Section>
      )}

      {/* Hierarchy */}
      <Section title="Hierarchy">
        {data.superclasses.length > 0 && (
          <div style={{ marginBottom: 10 }}>
            <div style={{ color: 'var(--text-dim)', fontSize: 11, marginBottom: 4 }}>Superclasses</div>
            {data.superclasses.map(iri => (
              <div key={iri} style={{ color: 'var(--accent)', fontSize: 'var(--font-size-sm)', paddingLeft: 8, marginBottom: 2 }}>
                <a href={`/browse/${oid}/${vid}?term=${encodeURIComponent(iri)}`}>
                  {iri.split(/[#/]/).pop()}
                </a>
              </div>
            ))}
          </div>
        )}
        {subclasses.length > 0 && (
          <div>
            <div style={{ color: 'var(--text-dim)', fontSize: 11, marginBottom: 4 }}>
              Subclasses ({subclasses.length})
            </div>
            <ul style={{ listStyle: 'none', columns: 2, gap: '0.5rem' }}>
              {subclasses.map(c => (
                <li key={c.iri} style={{ marginBottom: 4 }}>
                  <a
                    href={`/browse/${oid}/${vid}/term/${encodeURIComponent(c.iri)}`}
                    style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)' }}
                  >
                    {c.label ?? c.iri.split(/[#/]/).pop()}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Section>

      {/* Provenance */}
      <Section title="Provenance">
        <div style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
          Ontology: <span style={{ color: 'var(--text-muted)' }}>{oid}</span>
          {' · '}
          Version: <span style={{ color: 'var(--text-muted)' }}>{vid}</span>
        </div>
      </Section>
    </div>
  )
}
