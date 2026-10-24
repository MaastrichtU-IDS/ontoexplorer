import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { submissionOutcome } from '../lib/submissions'

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

function Chip({ label, color }: { label: string; color: string }) {
  return (
    <span style={{
      display: 'inline-block', padding: '0.05rem 0.5rem', borderRadius: 999,
      fontSize: 'var(--font-size-sm)', fontWeight: 600, color,
      border: `1px solid ${color}`, whiteSpace: 'nowrap',
    }}>
      {label}
    </span>
  )
}

export default function Submissions() {
  const { data, isLoading } = useQuery({
    queryKey: ['submissions'],
    queryFn: () => api.ontologies.submissions(),
    // Keep the list live while anything is still processing.
    refetchInterval: (q) => {
      const subs = q.state.data?.submissions ?? []
      return subs.some((s) => !submissionOutcome(s).done) ? 4000 : false
    },
  })
  const subs = data?.submissions ?? []

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
        <h1 style={{ fontSize: '1.1rem', fontWeight: 700 }}>Submissions</h1>
        <Link
          to="/dashboard"
          style={{
            padding: '0.35rem 0.8rem', background: 'var(--accent)', color: 'var(--bg)',
            borderRadius: 'var(--radius-sm)', fontWeight: 600, fontSize: 'var(--font-size-sm)',
            textDecoration: 'none',
          }}
        >
          + Add Ontology
        </Link>
      </div>
      <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', marginBottom: '1rem' }}>
        Every ontology you submit, with its outcome. Tracking survives leaving this page.
      </p>

      {isLoading ? (
        <p style={{ color: 'var(--text-dim)' }}>Loading…</p>
      ) : subs.length === 0 ? (
        <p style={{
          padding: '2rem', textAlign: 'center', color: 'var(--text-dim)',
          fontSize: 'var(--font-size-sm)', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
        }}>
          No submissions yet.
        </p>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
          <thead>
            <tr style={{ textAlign: 'left', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
              <th style={{ padding: '0.5rem 0.75rem' }}>Submitted</th>
              <th style={{ padding: '0.5rem 0.75rem' }}>Ontology</th>
              <th style={{ padding: '0.5rem 0.75rem' }}>Status</th>
              <th style={{ padding: '0.5rem 0.75rem' }} />
            </tr>
          </thead>
          <tbody>
            {subs.map((s) => {
              const o = submissionOutcome(s)
              const name = s.ontology?.title || s.ontology?.shortname || '(pending)'
              return (
                <tr key={s.task_id} style={{ borderTop: '1px solid var(--border)' }}>
                  <td style={{ padding: '0.5rem 0.75rem', color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', whiteSpace: 'nowrap' }}>
                    {fmtDate(s.created_at)}
                  </td>
                  <td style={{ padding: '0.5rem 0.75rem' }}>
                    {s.ontology ? (
                      <Link to={`/ontologies/${s.ontology.shortname}`} style={{ color: 'var(--accent)', textDecoration: 'none' }}>
                        {name}
                      </Link>
                    ) : (
                      <span style={{ color: 'var(--text-dim)' }}>{name}</span>
                    )}
                  </td>
                  <td style={{ padding: '0.5rem 0.75rem' }}>
                    <Chip label={o.label} color={o.color} />
                  </td>
                  <td style={{ padding: '0.5rem 0.75rem', textAlign: 'right' }}>
                    <Link to={`/dashboard/submissions/${s.task_id}`} style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)' }}>
                      Details →
                    </Link>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}
