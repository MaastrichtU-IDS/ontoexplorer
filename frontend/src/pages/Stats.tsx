import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../lib/api'

export default function Stats() {
  const { data, isLoading } = useQuery({ queryKey: ['stats'], queryFn: () => api.stats.get() })

  if (isLoading) return <p style={{ color: 'var(--text-dim)' }}>Loading…</p>

  const uploads = data?.uploads_per_month ?? []
  const queries = data?.queries_per_month ?? []
  const jobDurations = data?.job_durations ?? []

  return (
    <div>
      <h1 style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: '1rem' }}>Usage Stats</h1>

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
              cursor={{ fill: 'rgba(255,255,255,0.04)' }}
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
