import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { ApiError, api, type Submission } from '../lib/api'
import { submissionOutcome } from '../lib/submissions'

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString()
}

export default function SubmissionDetail() {
  const { taskId = '' } = useParams()

  const { data, isLoading, error } = useQuery<Submission>({
    queryKey: ['submission', taskId],
    queryFn: async () => {
      try {
        return await api.ontologies.submission(taskId)
      } catch (e) {
        // The worker writes the job row a moment after the task is queued, so a
        // just-submitted task 404s briefly. Treat that as "still queued" and keep
        // polling rather than erroring; any other failure propagates.
        if (e instanceof ApiError && e.status === 404) {
          return { task_id: taskId, job_status: 'pending', created_at: null,
                   finished_at: null, error: null, ontology: null, version: null }
        }
        throw e
      }
    },
    refetchInterval: (q) => (q.state.data && submissionOutcome(q.state.data).done ? false : 2500),
  })

  const back = (
    <Link to="/dashboard/submissions" style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)' }}>
      ← All submissions
    </Link>
  )

  if (isLoading) {
    return <div>{back}<p style={{ color: 'var(--text-dim)', marginTop: '1rem' }}>Loading…</p></div>
  }
  if (error || !data) {
    return (
      <div>
        {back}
        <p style={{ color: 'var(--red)', marginTop: '1rem' }}>
          {error instanceof Error ? error.message : 'Submission not found.'}
        </p>
      </div>
    )
  }

  const o = submissionOutcome(data)
  const held = data.version?.status === 'needs_review'

  return (
    <div style={{ maxWidth: 640 }}>
      {back}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', margin: '1rem 0 0.25rem' }}>
        <h1 style={{ fontSize: '1.1rem', fontWeight: 700 }}>
          {data.ontology?.title || data.ontology?.shortname || 'Submission'}
        </h1>
        <span style={{
          padding: '0.1rem 0.55rem', borderRadius: 999, fontSize: 'var(--font-size-sm)',
          fontWeight: 700, color: o.color, border: `1px solid ${o.color}`,
        }}>
          {o.label}
        </span>
        {!o.done && (
          <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>· refreshing…</span>
        )}
      </div>

      <dl style={{
        display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '0.35rem 1rem',
        margin: '1rem 0', fontSize: 'var(--font-size-sm)',
      }}>
        <dt style={{ color: 'var(--text-dim)' }}>Submitted</dt>
        <dd>{fmtDate(data.created_at)}</dd>
        <dt style={{ color: 'var(--text-dim)' }}>Finished</dt>
        <dd>{fmtDate(data.finished_at)}</dd>
        <dt style={{ color: 'var(--text-dim)' }}>Task ID</dt>
        <dd style={{ fontFamily: 'monospace', color: 'var(--text-muted)' }}>{data.task_id}</dd>
      </dl>

      {data.job_status === 'failed' && data.error && (
        <pre style={{
          whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: 'var(--red)',
          background: 'var(--bg-secondary)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius)', padding: '0.75rem', fontSize: 'var(--font-size-sm)',
        }}>
          {data.error}
        </pre>
      )}

      {held && (
        <div style={{
          background: 'var(--bg-secondary)', border: '1px solid var(--orange)',
          borderRadius: 'var(--radius)', padding: '0.85rem', fontSize: 'var(--font-size-sm)',
        }}>
          <p style={{ marginBottom: '0.6rem' }}>
            This submission needs a quick fix (a compliant license, a title) before it
            can be published. Resolve it on your dashboard — no re-upload needed in most cases.
          </p>
          <Link to="/dashboard" style={{
            display: 'inline-block', padding: '0.3rem 0.8rem', background: 'var(--orange)',
            color: 'var(--bg)', borderRadius: 'var(--radius-sm)', fontWeight: 600, textDecoration: 'none',
          }}>
            Fix it on the dashboard →
          </Link>
        </div>
      )}

      {data.version?.status === 'ready' && data.ontology && (
        <Link to={`/ontologies/${data.ontology.shortname}`} style={{
          display: 'inline-block', padding: '0.3rem 0.8rem', background: 'var(--accent)',
          color: 'var(--bg)', borderRadius: 'var(--radius-sm)', fontWeight: 600, textDecoration: 'none',
        }}>
          View published ontology →
        </Link>
      )}
    </div>
  )
}
