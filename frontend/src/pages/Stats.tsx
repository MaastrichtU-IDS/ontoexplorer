import { useState, type CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, UsageCounts, UsageTrendPoint } from '../lib/api'
import OntologyPicker from '../components/OntologyPicker'

export default function Stats() {
  const { data, isLoading } = useQuery({ queryKey: ['stats'], queryFn: () => api.stats.get() })

  if (isLoading) return <p style={{ color: 'var(--text-dim)' }}>Loading…</p>

  const uploads = data?.uploads_per_month ?? []
  const queries = data?.queries_per_month ?? []
  const jobDurations = data?.job_durations ?? []

  return (
    <div>
      <h1 style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: '1rem' }}>Usage Stats</h1>

      <UsageSection />

      <UsageTimeseriesWidget />

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '0.75rem', marginBottom: '1.25rem' }}>
        <StatCard label="Total ontologies" value={data?.total_ontologies ?? 0} />
        <StatCard label="Total versions" value={data?.total_versions ?? 0} />
        <StatCard label="Storage used" value={formatBytes(data?.storage_bytes ?? 0)} />
      </div>

      <ChartPanel title="Uploads per month" data={uploads} dataKey="count" xKey="month" color="var(--accent-blue)" />
      <ChartPanel title="Queries per month" data={queries} dataKey="count" xKey="month" color="var(--accent-purple)" />
      <ChartPanel title="Avg reasoning job duration (s)" data={jobDurations} dataKey="avg_seconds" xKey="month" color="var(--accent)" />
    </div>
  )
}

const GRANULARITIES = ['week', 'month', 'year'] as const
type Granularity = typeof GRANULARITIES[number]

function UsageSection() {
  const [gran, setGran] = useState<Granularity>('month')
  const { data, isLoading } = useQuery({
    queryKey: ['usage-public', gran],
    queryFn: () => api.stats.usagePublic(gran, 12),
  })
  const trend = data?.trend ?? []
  const hasData = trend.some(d => d.view_total || d.download_total)

  return (
    <div style={{ marginBottom: '1.5rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
        <h2 style={{ fontSize: 'var(--font-size-sm)', fontWeight: 600, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Views &amp; Downloads
        </h2>
        <div style={{ display: 'flex', gap: 4 }}>
          {GRANULARITIES.map(g => (
            <button
              key={g}
              onClick={() => setGran(g)}
              style={{
                fontSize: 11, textTransform: 'capitalize', cursor: 'pointer',
                padding: '3px 10px', borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border)',
                background: g === gran ? 'var(--accent)' : 'transparent',
                color: g === gran ? 'var(--on-accent)' : 'var(--text-dim)',
              }}
            >{g}</button>
          ))}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '0.75rem' }}>
        <DualStatCard label="Views" counts={data?.totals.views} />
        <DualStatCard label="Downloads" counts={data?.totals.downloads} />
      </div>

      <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1rem' }}>
        <h2 style={{ fontSize: 'var(--font-size-sm)', fontWeight: 600, color: 'var(--text-dim)', marginBottom: '1rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Unique per {gran}
        </h2>
        {isLoading ? (
          <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>Loading…</p>
        ) : !hasData ? (
          <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>No data yet.</p>
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={trend as UsageTrendPoint[]}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="period" tick={{ fontSize: 11, fill: 'var(--text-dim)' }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: 'var(--text-dim)' }} axisLine={false} tickLine={false} allowDecimals={false} />
              <Tooltip contentStyle={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', fontSize: '0.8rem', color: 'var(--text)' }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line type="monotone" dataKey="view_unique" name="Views" stroke="var(--accent-blue)" dot={false} strokeWidth={2} />
              <Line type="monotone" dataKey="download_unique" name="Downloads" stroke="var(--accent)" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}

const SERIES_COLORS = ['var(--accent-blue)', 'var(--accent)', 'var(--accent-purple)', 'var(--orange)', 'var(--green)']
const MAX_ONTOLOGIES = 5

function UsageTimeseriesWidget() {
  const [ids, setIds] = useState<string[]>([])
  const [kind, setKind] = useState<'view' | 'download'>('view')
  const [gran, setGran] = useState<Granularity>('month')

  const { data, isLoading } = useQuery({
    queryKey: ['usage-timeseries', ids, kind, gran],
    queryFn: () => api.stats.usageTimeseries(ids, kind, gran, 12),
    enabled: ids.length > 0,
  })

  // Merge the per-ontology series into one row-per-period array for recharts,
  // keyed by ontology_id (plotting the unique count).
  const series = data?.series ?? []
  const periods = data?.periods ?? []
  const chartData = periods.map((p, i) => {
    const row: Record<string, string | number> = { period: p }
    for (const s of series) row[s.ontology_id] = s.points[i]?.unique ?? 0
    return row
  })

  return (
    <div style={{ marginBottom: '1.5rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem', gap: 8, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 'var(--font-size-sm)', fontWeight: 600, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Compare ontologies over time
        </h2>
        <div style={{ display: 'flex', gap: 12 }}>
          <div style={{ display: 'flex', gap: 4 }}>
            {(['view', 'download'] as const).map(k => (
              <button key={k} onClick={() => setKind(k)} style={toggleStyle(k === kind)}>
                {k === 'view' ? 'Views' : 'Downloads'}
              </button>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 4 }}>
            {GRANULARITIES.map(g => (
              <button key={g} onClick={() => setGran(g)} style={{ ...toggleStyle(g === gran), textTransform: 'capitalize' }}>{g}</button>
            ))}
          </div>
        </div>
      </div>

      <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1rem' }}>
        <OntologyPicker
          value={ids}
          onChange={next => setIds(next.slice(0, MAX_ONTOLOGIES))}
          placeholder={`Add up to ${MAX_ONTOLOGIES} ontologies to compare…`}
        />
        {ids.length >= MAX_ONTOLOGIES && (
          <p style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: 4 }}>Maximum of {MAX_ONTOLOGIES} ontologies.</p>
        )}

        <div style={{ marginTop: '1rem' }}>
          {ids.length === 0 ? (
            <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>Select one or more ontologies to compare their {kind === 'view' ? 'views' : 'downloads'} per {gran}.</p>
          ) : isLoading ? (
            <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>Loading…</p>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="period" tick={{ fontSize: 11, fill: 'var(--text-dim)' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fill: 'var(--text-dim)' }} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip contentStyle={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', fontSize: '0.8rem', color: 'var(--text)' }} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                {series.map((s, i) => (
                  <Line key={s.ontology_id} type="monotone" dataKey={s.ontology_id} name={s.label}
                        stroke={SERIES_COLORS[i % SERIES_COLORS.length]} dot={false} strokeWidth={2} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>
    </div>
  )
}

function toggleStyle(active: boolean): CSSProperties {
  return {
    fontSize: 11, cursor: 'pointer', padding: '3px 10px', borderRadius: 'var(--radius-sm)',
    border: '1px solid var(--border)',
    background: active ? 'var(--accent)' : 'transparent',
    color: active ? 'var(--on-accent)' : 'var(--text-dim)',
  }
}

function DualStatCard({ label, counts }: { label: string; counts?: UsageCounts }) {
  return (
    <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1rem' }}>
      <p style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)', marginBottom: '0.25rem', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>
        {label}
      </p>
      <p style={{ fontSize: '1.75rem', fontWeight: 700, color: 'var(--text)' }}>
        {(counts?.unique ?? 0).toLocaleString()}
        <span style={{ fontSize: '0.9rem', fontWeight: 500, color: 'var(--text-dim)' }}>
          {' '}/ {(counts?.total ?? 0).toLocaleString()} total
        </span>
      </p>
      <p style={{ fontSize: 11, color: 'var(--text-dim)' }}>unique</p>
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div style={{
      background: 'var(--bg-secondary)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius)',
      padding: '1rem',
    }}>
      <p style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)', marginBottom: '0.25rem', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>
        {label}
      </p>
      <p style={{ fontSize: '1.75rem', fontWeight: 700, color: 'var(--text)' }}>{value}</p>
    </div>
  )
}

function ChartPanel({ title, data, dataKey, xKey, color }: {
  title: string
  data: Record<string, unknown>[]
  dataKey: string
  xKey: string
  color: string
}) {
  return (
    <div style={{
      background: 'var(--bg-secondary)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius)',
      padding: '1rem',
      marginBottom: '0.75rem',
    }}>
      <h2 style={{ fontSize: 'var(--font-size-sm)', fontWeight: 600, color: 'var(--text-dim)', marginBottom: '1rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        {title}
      </h2>
      {data.length === 0 ? (
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>No data yet.</p>
      ) : (
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey={xKey} tick={{ fontSize: 11, fill: 'var(--text-dim)' }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 11, fill: 'var(--text-dim)' }} axisLine={false} tickLine={false} />
            <Tooltip
              contentStyle={{
                background: 'var(--bg-secondary)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-sm)',
                fontSize: '0.8rem',
                color: 'var(--text)',
              }}
              cursor={{ fill: 'var(--overlay)' }}
            />
            <Bar dataKey={dataKey} fill={color} radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`
}
