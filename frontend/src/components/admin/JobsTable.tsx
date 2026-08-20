import React from 'react'
import { AdminJobEntry } from '../../lib/api'
import { usePagedTable } from '../../hooks/usePagedTable'
import { TablePager } from '../TablePager'
import {
  JOB_TYPE_COLOR,
  StatusDot,
  fmtAge,
  fmtDuration,
} from './shared'

export function JobsTable({ jobs }: { jobs: AdminJobEntry[] }) {
  const { paged, page, setPage, pageSize, setPageSize, total } = usePagedTable(jobs, 'jobs')

  return (
    <div>
      <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, overflowX: 'auto' }}>
        <table style={{ width: '100%', minWidth: 560, borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg)' }}>
              {['Type', 'Ontology', 'Status', 'Duration', 'Started'].map(h => (
                <th key={h} style={{ padding: '7px 10px', textAlign: h === 'Type' || h === 'Ontology' ? 'left' : 'center', color: 'var(--text-dim)', fontWeight: 500, fontSize: 10, textTransform: 'uppercase', letterSpacing: .5 }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {paged.map(job => (
              <React.Fragment key={job.id}>
              <tr style={{
                borderBottom: job.error ? undefined : '1px solid var(--overlay)',
                background: job.status === 'failed' ? 'rgba(248,81,73,0.06)' : undefined,
              }}>
                <td style={{ padding: '6px 10px', color: JOB_TYPE_COLOR[job.type] ?? 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase', fontWeight: 600 }}>
                  {job.type}
                </td>
                <td style={{ padding: '6px 10px', color: 'var(--text)' }}>
                  {job.ontology_shortname ?? job.ontology_iri?.split(/[/#]/).pop() ?? '—'}
                </td>
                <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                  <StatusDot status={job.status} />
                </td>
                <td style={{ padding: '6px 10px', textAlign: 'center', color: 'var(--text-muted)' }}>
                  {fmtDuration(job.started_at, job.finished_at)}
                  {job.status === 'running' && <span style={{ color: 'var(--text-dim)' }}>…</span>}
                </td>
                <td style={{ padding: '6px 10px', textAlign: 'center', color: 'var(--text-dim)', fontSize: 11 }}>
                  {fmtAge(job.started_at)}
                </td>
              </tr>
              {job.error && (
                // The only place the UI accounts for *why* a job failed. An
                // ingestion that died before producing a version has no
                // ontology page to carry the message.
                <tr style={{
                  borderBottom: '1px solid var(--overlay)',
                  background: job.status === 'failed' ? 'rgba(248,81,73,0.06)' : undefined,
                }}>
                  <td colSpan={5} style={{
                    padding: '0 10px 7px 10px',
                    color: 'var(--danger, #f85149)',
                    fontFamily: 'var(--font-mono, monospace)',
                    fontSize: 11,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}>
                    {job.error}
                  </td>
                </tr>
              )}
              </React.Fragment>
            ))}
            {paged.length === 0 && (
              <tr>
                <td colSpan={5} style={{ padding: '16px', textAlign: 'center', color: 'var(--text-dim)' }}>
                  No jobs yet
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <TablePager total={total} page={page} pageSize={pageSize} onPage={setPage} onPageSize={setPageSize} />
    </div>
  )
}
