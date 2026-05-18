import { useQuery } from '@tanstack/react-query'
import { api, CoverageEntityType, CoverageRecord } from '../lib/api'

const TYPE_LABELS: Record<CoverageEntityType, string> = {
  class:               'Classes',
  object_property:     'Object properties',
  data_property:       'Data properties',
  annotation_property: 'Annotation properties',
  individual:          'Individuals',
}

const TYPE_ORDER: CoverageEntityType[] = [
  'class', 'object_property', 'data_property', 'annotation_property', 'individual',
]

function pct(num: number, denom: number): string {
  if (denom <= 0) return '—'
  return `${Math.round((num / denom) * 100)}%`
}

export default function CoverageSection({ ontologyId, versionId }: {
  ontologyId: string; versionId: string
}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['coverage', 'version', versionId],
    queryFn: () => api.coverage.version(ontologyId, versionId),
    retry: false,
  })

  if (isLoading) return <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>Loading…</div>

  if (error || !data) {
    return (
      <section id="coverage" style={{ padding: '1rem' }}>
        <h2 style={{ fontSize: '0.95rem', fontWeight: 600, marginBottom: '0.5rem' }}>Coverage</h2>
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
          Coverage not yet computed — will be available after the next reindex.
        </p>
      </section>
    )
  }

  const record = data as CoverageRecord
  const classByLang = record.by_type.class.by_lang
  const classTotal = record.by_type.class.total

  return (
    <section id="coverage" style={{ padding: '1rem' }}>
      <h2 style={{ fontSize: '0.95rem', fontWeight: 600, marginBottom: '0.5rem' }}>Coverage</h2>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '0.5rem', marginBottom: '1rem' }}>
        {TYPE_ORDER.map(t => {
          const b = record.by_type[t]
          return (
            <div key={t} data-testid={`coverage-card-${t}`} style={{
              background: 'var(--bg-secondary)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius)', padding: '0.6rem 0.75rem',
            }}>
              <div style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>
                {TYPE_LABELS[t]} ({b.total.toLocaleString()})
              </div>
              <Metric label="Label"     pct={pct(b.with_label, b.total)}      count={b.with_label} />
              <Metric label="Def"       pct={pct(b.with_definition, b.total)} count={b.with_definition} />
              <Metric label="Multilang" pct={pct(b.multilingual, b.total)}    count={b.multilingual} />
            </div>
          )
        })}
      </div>

      {classTotal > 0 && Object.keys(classByLang).length > 0 && (
        <div data-testid="lang-bar">
          <div style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>
            Class label languages
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {Object.entries(classByLang)
              .sort((a, b) => b[1] - a[1])
              .map(([tag, n]) => (
                <span key={tag} style={{
                  fontSize: 11, padding: '2px 8px', borderRadius: 3,
                  background: 'rgba(80,160,255,0.12)', color: 'var(--accent-blue)',
                }}>
                  {tag || '(no lang)'}: {n.toLocaleString()} ({pct(n, classTotal)})
                </span>
              ))}
          </div>
        </div>
      )}

      <p style={{ marginTop: '0.75rem', color: 'var(--text-muted)', fontSize: 11 }}>
        Last computed: {new Date(record.indexed_at).toLocaleString()}
      </p>
    </section>
  )
}

function Metric({ label, pct, count }: { label: string; pct: string; count: number }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginTop: 2 }}>
      <span style={{ color: 'var(--text-dim)' }}>{label}</span>
      <span style={{ color: 'var(--text)' }}>{pct} <span style={{ color: 'var(--text-muted)' }}>({count.toLocaleString()})</span></span>
    </div>
  )
}
