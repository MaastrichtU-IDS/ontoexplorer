import type { Submission } from './api'

// Map a submission (job status + the version it produced) to the single outcome a
// contributor sees. `done` = the pipeline has settled, so a tracker can stop
// polling. The vocabulary matches the dashboard inbox (never raw "needs_review").
export interface SubmissionOutcome {
  label: string
  color: string
  done: boolean
}

export function submissionOutcome(s: Submission): SubmissionOutcome {
  if (s.job_status === 'failed') return { label: 'Failed', color: 'var(--red)', done: true }
  const v = s.version
  if (!v) return { label: 'Processing', color: 'var(--accent)', done: false }
  switch (v.status) {
    case 'ready':
      return { label: 'Published', color: 'var(--green)', done: true }
    case 'needs_review':
      return { label: 'Needs your attention', color: 'var(--orange)', done: true }
    case 'deprecated':
      return { label: 'Deprecated', color: 'var(--text-dim)', done: true }
    case 'pending':
    case 'ingested':
      return { label: 'Processing', color: 'var(--accent)', done: false }
    default:
      return { label: v.status, color: 'var(--text-muted)', done: true }
  }
}
