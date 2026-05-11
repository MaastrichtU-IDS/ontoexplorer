import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../lib/api'

export default function Stats() {
  const { data, isLoading } = useQuery({ queryKey: ['stats'], queryFn: () => api.stats.get() })

  if (isLoading) return <p style={{ color: '#64748b' }}>Loading…</p>

  const uploads = data?.uploads_per_month ?? []
  const queries = data?.queries_per_month ?? []
  const jobDurations = data?.job_durations ?? []

  return (
    <div>
      <h1 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '1.5rem' }}>Usage Stats</h1>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem', marginBottom: '1.5rem' }}>
        <StatCard label="Total ontologies" value={data?.total_ontologies ?? 0} />
        <StatCard label="Total versions" value={data?.total_versions ?? 0} />
        <StatCard label="Storage used" value={formatBytes(data?.storage_bytes ?? 0)} />
        <StatCard label="Total queries" value={data?.total_queries ?? 0} />
      </div>

      <ChartPanel title="Uploads per month" data={uploads} dataKey="count" xKey="month" color="#2563eb" />
      <ChartPanel title="Queries per month" data={queries} dataKey="count" xKey="month" color="#7c3aed" />
      <ChartPanel title="Avg reasoning job duration (s)" data={jobDurations} dataKey="avg_seconds" xKey="month" color="#059669" />
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, padding: '1.25rem' }}>
      <p style={{ fontSize: '0.8rem', color: '#64748b', marginBottom: '0.25rem' }}>{label}</p>
      <p style={{ fontSize: '1.75rem', fontWeight: 700, color: '#1e293b' }}>{value}</p>
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
    <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, padding: '1.25rem', marginBottom: '1.5rem' }}>
      <h2 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>{title}</h2>
      {data.length === 0 ? (
        <p style={{ color: '#94a3b8', fontSize: '0.875rem' }}>No data yet.</p>
      ) : (
        <ResponsiveContainer width="100%" height={200}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
            <XAxis dataKey={xKey} tick={{ fontSize: 11, fill: '#64748b' }} />
            <YAxis tick={{ fontSize: 11, fill: '#64748b' }} />
            <Tooltip contentStyle={{ fontSize: '0.8rem' }} />
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
