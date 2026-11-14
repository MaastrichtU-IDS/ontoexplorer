import { useQuery } from '@tanstack/react-query'
import { api, FairFleet } from '../lib/api'

const PRINCIPLE_NAMES: Record<string, string> = {
  F: 'Findable', A: 'Accessible', I: 'Interoperable', R: 'Reusable',
}
const BUCKET_COLOR: Record<string, string> = {
  '<50': 'var(--red)', '50-69': 'var(--orange)', '70-84': 'var(--orange)', '85-100': 'var(--green)',
}

function scoreColor(pct: number): string {
  return pct >= 85 ? 'var(--green)' : pct >= 50 ? 'var(--orange)' : 'var(--red)'
}

export default function FairOverview() {
  const { data, isLoading, error } = useQuery<FairFleet>({
    queryKey: ['fair-fleet'],
    queryFn: () => api.fair.fleet(),
  })

  if (isLoading) return <div style={{ color: 'var(--text-dim)' }}>Loading…</div>
  if (error || !data) return <div>Failed to load fleet FAIR data.</div>

  const maxCount = Math.max(1, ...data.overall_histogram.map(b => b.count))

  return (
    <div data-testid="fair-overview" style={{ display: 'flex', flexDirection: 'column', gap: 24, maxWidth: 820 }}>
      <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', margin: 0 }}>
        FAIR assessment across <b>{data.n}</b> ready versions — aligned with the FOOPS! check set,
        scored from signals computed at ingest.
      </p>

      <section>
        <h3 style={{ fontSize: 14, fontWeight: 600, margin: '0 0 10px' }}>Overall score distribution</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {data.overall_histogram.map(b => (
            <div key={b.bucket} style={{ display: 'grid', gridTemplateColumns: '70px 1fr 54px', gap: 10, alignItems: 'center' }}>
              <span style={{ fontSize: 12.5, color: 'var(--text-dim)' }}>{b.bucket}</span>
              <span style={{ height: 14, borderRadius: 4, background: 'var(--bg-tertiary)', overflow: 'hidden' }}>
                <span style={{ display: 'block', height: '100%', width: `${(b.count / maxCount) * 100}%`, background: BUCKET_COLOR[b.bucket] ?? 'var(--accent)' }} />
              </span>
              <span style={{ fontFamily: 'monospace', fontSize: 12.5, fontWeight: 600, textAlign: 'right' }}>{b.count}</span>
            </div>
          ))}
        </div>
      </section>

      <section>
        <h3 style={{ fontSize: 14, fontWeight: 600, margin: '0 0 10px' }}>Mean score by principle</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {['F', 'A', 'I', 'R'].map(k => {
            const pct = Math.round((data.principle_means[k] ?? 0) * 100)
            return (
              <div key={k} style={{ display: 'grid', gridTemplateColumns: '120px 1fr 40px', gap: 10, alignItems: 'center' }}>
                <span style={{ fontSize: 12.5, color: 'var(--text-dim)' }}><b style={{ color: 'var(--text)' }}>{k}</b> {PRINCIPLE_NAMES[k]}</span>
                <span style={{ height: 8, borderRadius: 5, background: 'var(--bg-tertiary)', overflow: 'hidden' }}>
                  <span style={{ display: 'block', height: '100%', width: `${pct}%`, background: scoreColor(pct) }} />
                </span>
                <span style={{ fontFamily: 'monospace', fontSize: 12.5, fontWeight: 600, textAlign: 'right', color: scoreColor(pct) }}>{pct}</span>
              </div>
            )
          })}
        </div>
      </section>

      <section>
        <h3 style={{ fontSize: 14, fontWeight: 600, margin: '0 0 10px' }}>Pass rate by check</h3>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {data.check_pass_rate.map(c => {
            const pct = Math.round(c.rate * 100)
            return (
              <div key={c.id} data-testid={`fair-rate-${c.id}`} style={{ display: 'grid', gridTemplateColumns: '1fr 120px 48px', gap: 10, alignItems: 'center', padding: '7px 0', borderTop: '1px solid var(--border)' }}>
                <span style={{ fontSize: 12.5 }}>
                  <span style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--text-dim)', marginRight: 6 }}>{c.id}</span>
                  {c.name}
                </span>
                <span style={{ height: 6, borderRadius: 4, background: 'var(--bg-tertiary)', overflow: 'hidden' }}>
                  <span style={{ display: 'block', height: '100%', width: `${pct}%`, background: scoreColor(pct) }} />
                </span>
                <span style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 600, textAlign: 'right' }}>{pct}%</span>
              </div>
            )
          })}
        </div>
      </section>
    </div>
  )
}
