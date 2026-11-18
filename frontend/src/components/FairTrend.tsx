import { useQuery } from '@tanstack/react-query'
import { api, FairHistory } from '../lib/api'

// Distinct, theme-independent hues for the four principle lines (readable on both
// light and dark). Overall uses the page accent and is drawn prominently.
const SERIES: { key: string; label: string; color: string }[] = [
  { key: 'F', label: 'Findable', color: '#5b8def' },
  { key: 'A', label: 'Accessible', color: '#2bb3a3' },
  { key: 'I', label: 'Interoperable', color: '#e8a33d' },
  { key: 'R', label: 'Reusable', color: '#c678dd' },
]

const W = 720
const H = 240
const PAD = { top: 12, right: 14, bottom: 26, left: 30 }

function fmtDay(iso: string): string {
  const d = new Date(iso + 'T00:00:00Z')
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' })
}

export default function FairTrend() {
  const { data, isLoading, error } = useQuery<FairHistory>({
    queryKey: ['fair-history'],
    queryFn: () => api.fair.history(365),
  })

  if (isLoading) return <div style={{ color: 'var(--text-dim)', fontSize: 13 }}>Loading trend…</div>
  if (error || !data) return null
  const series = data.series

  if (series.length < 2) {
    return (
      <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', margin: 0 }}>
        The fairness trend appears once at least two daily snapshots have been captured
        {series.length === 1 ? ` (first snapshot: ${fmtDay(series[0].day)})` : ''}.
      </p>
    )
  }

  const n = series.length
  const plotW = W - PAD.left - PAD.right
  const plotH = H - PAD.top - PAD.bottom
  const x = (i: number) => PAD.left + (n === 1 ? plotW / 2 : (i / (n - 1)) * plotW)
  const y = (pct: number) => PAD.top + (1 - Math.max(0, Math.min(100, pct)) / 100) * plotH

  const line = (vals: number[]) =>
    vals.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')

  const overall = series.map(s => (s.overall_mean ?? 0) * 100)
  const upper = series.map(s => ((s.overall_mean ?? 0) + (s.overall_stddev ?? 0)) * 100)
  const lower = series.map(s => ((s.overall_mean ?? 0) - (s.overall_stddev ?? 0)) * 100)
  const bandPts =
    upper.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ') + ' ' +
    lower.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).reverse().join(' ')

  const latest = series[n - 1]

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, marginBottom: 8 }}>
        <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
          {n} snapshot{n === 1 ? '' : 's'} · {fmtDay(series[0].day)} – {fmtDay(latest.day)}
        </span>
        <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
          latest overall <b style={{ color: 'var(--text)' }}>{Math.round((latest.overall_mean ?? 0) * 100)}</b>
          {' '}<span style={{ fontFamily: 'monospace' }}>± {Math.round((latest.overall_stddev ?? 0) * 100)}</span>
        </span>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img"
        aria-label="Fleet FAIR score over time" style={{ maxWidth: '100%', overflow: 'visible' }}>
        {/* y gridlines + labels */}
        {[0, 25, 50, 75, 100].map(g => (
          <g key={g}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(g)} y2={y(g)}
              stroke="var(--border)" strokeWidth={1} strokeDasharray={g === 0 ? undefined : '2 3'} />
            <text x={PAD.left - 6} y={y(g) + 3} textAnchor="end"
              fontSize={10} fill="var(--text-dim)">{g}</text>
          </g>
        ))}
        {/* ±SD band around the overall mean */}
        <polygon points={bandPts} fill="var(--accent)" opacity={0.12} />
        {/* principle lines */}
        {SERIES.map(s => (
          <polyline key={s.key} fill="none" stroke={s.color} strokeWidth={1.25} opacity={0.9}
            points={line(series.map(p => (p.principle_means?.[s.key] ?? 0) * 100))} />
        ))}
        {/* overall mean, drawn on top */}
        <polyline fill="none" stroke="var(--accent)" strokeWidth={2.5}
          points={line(overall)} />
        {/* x end labels */}
        <text x={PAD.left} y={H - 8} fontSize={10} fill="var(--text-dim)">{fmtDay(series[0].day)}</text>
        <text x={W - PAD.right} y={H - 8} textAnchor="end" fontSize={10} fill="var(--text-dim)">{fmtDay(latest.day)}</text>
      </svg>

      {/* legend */}
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 8 }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-dim)' }}>
          <span style={{ width: 16, height: 3, background: 'var(--accent)', borderRadius: 2 }} />Overall
        </span>
        {SERIES.map(s => (
          <span key={s.key} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-dim)' }}>
            <span style={{ width: 16, height: 2, background: s.color, borderRadius: 2 }} />{s.label}
          </span>
        ))}
      </div>
    </div>
  )
}
