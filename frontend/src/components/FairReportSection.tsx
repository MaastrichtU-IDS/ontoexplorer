import { useQuery } from '@tanstack/react-query'
import { api, FairCheck, FairReport } from '../lib/api'

const PRINCIPLE_NAMES: Record<string, string> = {
  F: 'Findable', A: 'Accessible', I: 'Interoperable', R: 'Reusable',
}

const STATUS: Record<FairCheck['status'], { color: string; glyph: string; label: string }> = {
  pass: { color: 'var(--green)', glyph: '✓', label: 'Pass' },
  partial: { color: 'var(--orange)', glyph: '◐', label: 'Partial' },
  fail: { color: 'var(--red)', glyph: '✕', label: 'Fail' },
}

function scoreColor(pct: number): string {
  return pct >= 85 ? 'var(--green)' : pct >= 50 ? 'var(--orange)' : 'var(--red)'
}

const sm = 'var(--font-size-sm)'

function StatusDot({ status }: { status: FairCheck['status'] }) {
  const s = STATUS[status]
  return (
    <span aria-label={s.label} title={s.label} style={{
      flex: 'none', width: 18, height: 18, borderRadius: '50%', display: 'inline-grid',
      placeItems: 'center', fontSize: 11, fontWeight: 800, color: s.color,
      background: 'var(--bg-tertiary)',
    }}>{s.glyph}</span>
  )
}

function RoleGrid({ detail }: { detail: NonNullable<FairCheck['detail']> }) {
  const scored = detail.roles.filter(r => !r.excluded)
  const excluded = detail.roles.filter(r => r.excluded)
  const render = (r: { role: string; predicates: string[]; filled: boolean; excluded: boolean }, i: number) => (
    <div key={i} data-testid="fair-role" style={{
      display: 'grid', gridTemplateColumns: '16px 1fr', gap: 8, alignItems: 'start',
      padding: '4px 0', borderTop: '1px solid var(--border)',
    }}>
      <span style={{
        marginTop: 2, color: r.excluded ? 'var(--text-dim)' : r.filled ? 'var(--green)' : 'var(--red)',
        fontWeight: 800, fontSize: 11,
      }}>{r.excluded ? '–' : r.filled ? '✓' : '✕'}</span>
      <div>
        <div style={{ fontSize: 12.5, color: r.filled && !r.excluded ? 'var(--text)' : 'var(--text-dim)' }}>{r.role}</div>
        <div style={{ marginTop: 1 }}>
          {r.predicates.map((p, j) => (
            <code key={j} style={{ fontSize: 10.5, color: 'var(--text-dim)', marginRight: 6 }}>{p}</code>
          ))}
        </div>
      </div>
    </div>
  )
  return (
    <div>
      <div style={{ fontSize: 10.5, letterSpacing: '.06em', textTransform: 'uppercase', color: 'var(--text-dim)', fontWeight: 600, margin: '10px 0 4px' }}>
        Scored metadata roles ({detail.scored})
      </div>
      <div style={{ color: 'var(--text-dim)', fontSize: 12, marginBottom: 4 }}>
        {detail.filled} / {detail.scored} filled
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0 22px' }}>
        {scored.map(render)}
      </div>
      {excluded.length > 0 && (
        <>
          <div style={{ fontSize: 10.5, letterSpacing: '.06em', textTransform: 'uppercase', color: 'var(--text-dim)', fontWeight: 600, margin: '12px 0 4px' }}>
            Optional — not scored ({excluded.length})
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0 22px' }}>
            {excluded.map(render)}
          </div>
        </>
      )}
    </div>
  )
}

function CheckRow({ check }: { check: FairCheck }) {
  return (
    <details data-testid={`fair-check-${check.id}`} style={{ borderTop: '1px solid var(--border)' }}>
      <summary style={{
        listStyle: 'none', cursor: 'pointer', display: 'grid',
        gridTemplateColumns: '22px 1fr', gap: 10, alignItems: 'start', padding: '10px 2px',
      }}>
        <StatusDot status={check.status} />
        <div>
          <div style={{ fontSize: 13.5, fontWeight: 500 }}>
            {check.name}
            <span style={{ fontFamily: 'monospace', fontSize: 10.5, color: 'var(--text-dim)', marginLeft: 6 }}>{check.id}</span>
          </div>
          <div style={{ color: 'var(--text-dim)', fontSize: 12.5, marginTop: 2 }}>{check.evidence}</div>
        </div>
      </summary>
      <div style={{ padding: '2px 2px 12px 32px' }}>
        {check.tests.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {check.tests.map(([label, value], i) => (
              <div key={i} style={{ display: 'grid', gridTemplateColumns: '150px 1fr', gap: 12 }}>
                <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>{label}</div>
                <div style={{ fontSize: 12.5 }}>{value}</div>
              </div>
            ))}
          </div>
        )}
        {check.detail && <RoleGrid detail={check.detail} />}
      </div>
    </details>
  )
}

function PrincipleGroup({ principle }: { principle: FairReport['principles'][number] }) {
  const pct = principle.score_pct
  return (
    <details data-testid={`fair-principle-${principle.principle}`} open style={{
      background: 'var(--bg-secondary)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius)', marginBottom: 12,
    }}>
      <summary style={{
        listStyle: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center',
        gap: 12, padding: '12px 14px',
      }}>
        <span style={{
          flex: 'none', width: 26, height: 26, borderRadius: 6, display: 'grid', placeItems: 'center',
          fontSize: 13, fontWeight: 700, color: 'var(--bg)', background: 'var(--accent)',
        }}>{principle.principle}</span>
        <span style={{ fontWeight: 600, fontSize: 14 }}>{PRINCIPLE_NAMES[principle.principle] ?? principle.principle}</span>
        <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>{principle.checks.length} checks</span>
        <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ width: 66, height: 6, borderRadius: 4, background: 'var(--bg-tertiary)', overflow: 'hidden' }}>
            <span style={{ display: 'block', height: '100%', width: `${pct}%`, background: scoreColor(pct) }} />
          </span>
          <span style={{ fontFamily: 'monospace', fontWeight: 600, fontSize: 13, color: scoreColor(pct), minWidth: 30, textAlign: 'right' }}>{pct}</span>
        </span>
      </summary>
      <div style={{ padding: '0 14px 6px', borderTop: '1px solid var(--border)' }}>
        {principle.checks.map(c => <CheckRow key={c.id} check={c} />)}
      </div>
    </details>
  )
}

export default function FairReportSection({ ontologyId, versionId }: {
  ontologyId: string; versionId: string
}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['fair', ontologyId, versionId],
    queryFn: () => api.fair.report(ontologyId, versionId),
    retry: false,
  })

  if (isLoading) {
    return <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: sm }}>Loading…</div>
  }

  if (error || !data) {
    const status = (error as { status?: number } | null)?.status
    return (
      <section id="fair" style={{ padding: '1rem' }}>
        <h2 style={{ fontSize: '0.95rem', fontWeight: 600, marginBottom: '0.5rem' }}>FAIR report</h2>
        <p style={{ color: 'var(--text-dim)', fontSize: sm }}>
          {status === 404
            ? 'FAIR report not yet computed — will be available after the next reindex.'
            : 'Could not load the FAIR report.'}
        </p>
      </section>
    )
  }

  const report = data as FairReport
  const oc = scoreColor(report.overall_pct)

  return (
    <section id="fair" style={{ padding: '1rem' }}>
      <h2 style={{ fontSize: '0.95rem', fontWeight: 600, marginBottom: '0.75rem' }}>FAIR report</h2>

      <div data-testid="fair-overall" style={{
        display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap',
        background: 'var(--bg-secondary)', border: '1px solid var(--border)',
        borderRadius: 'var(--radius)', padding: '14px 16px', marginBottom: 16,
      }}>
        <div>
          <span style={{ fontFamily: 'monospace', fontSize: 30, fontWeight: 600, color: oc }}>{report.overall_pct}</span>
          <span style={{ color: 'var(--text-dim)', fontSize: 12 }}> / 100</span>
          <div style={{ fontSize: 12.5, fontWeight: 600, color: oc }}>{report.verdict}</div>
          <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 2 }}>
            {Math.round(report.n_passed * 10) / 10} of {report.n_checks} checks
          </div>
        </div>
        <div style={{ flex: 1, minWidth: 180, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {report.principles.map(p => (
            <div key={p.principle} style={{ display: 'grid', gridTemplateColumns: '18px 1fr 34px', gap: 9, alignItems: 'center' }}>
              <span style={{ fontWeight: 700, fontSize: 12, color: 'var(--text-dim)' }}>{p.principle}</span>
              <span style={{ height: 7, borderRadius: 4, background: 'var(--bg-tertiary)', overflow: 'hidden' }}>
                <span style={{ display: 'block', height: '100%', width: `${p.score_pct}%`, background: scoreColor(p.score_pct) }} />
              </span>
              <span style={{ fontFamily: 'monospace', fontSize: 12.5, fontWeight: 600, textAlign: 'right', color: scoreColor(p.score_pct) }}>{p.score_pct}</span>
            </div>
          ))}
        </div>
      </div>

      {report.principles.map(p => <PrincipleGroup key={p.principle} principle={p} />)}

      <p style={{ color: 'var(--text-dim)', fontSize: 11.5, marginTop: 10 }}>
        Scored from signals computed at ingest (resolvability, licence, OWL profile, reuse,
        metadata, coverage); aligned with the FOOPS! check set. Each check expands to the exact
        tests it evaluates.
      </p>
    </section>
  )
}
