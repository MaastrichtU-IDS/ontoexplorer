import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { WorkerTask, api } from '../../lib/api'
import { usePagedTable } from '../../hooks/usePagedTable'
import { TablePager } from '../TablePager'
import { JOB_TYPE_COLOR, fmtDuration } from './shared'

const TASK_SHORT: Record<string, string> = {
  'ontoexplorer.ingest_ontology':    'ingest',
  'ontoexplorer.embed_ontology':     'embed',
  'ontoexplorer.index_ontology':     'index',
  'ontoexplorer.reason_ontology':    'reason',
  'ontoexplorer.detect_profile':     'profile',
  'ontoexplorer.detect_meta_profile':'meta',
  'ontoexplorer.compute_diff':       'diff',
  'ontoexplorer.poll_for_updates':   'poll',
}

function taskLabel(name: string): string {
  return TASK_SHORT[name] ?? name.split('.').pop() ?? name
}

function taskDetail(t: WorkerTask, versionMap: Record<string, string>): string {
  const kw = t.kwargs
  if (kw.version_id) {
    const name = versionMap[String(kw.version_id)]
    return name ?? String(kw.version_id).slice(0, 8) + '…'
  }
  if (kw.iri) return String(kw.iri).replace(/^https?:\/\//, '').slice(0, 48)
  if (kw.url) return String(kw.url).replace(/^https?:\/\//, '').slice(0, 48)
  return '—'
}

export function WorkersPanel({ versionMap }: { versionMap: Record<string, string> }) {
  const qc = useQueryClient()
  const [revoking, setRevoking] = useState<Set<string>>(new Set())

  const { data, isFetching } = useQuery({
    queryKey: ['admin-workers'],
    queryFn: () => api.admin.workers(),
    refetchInterval: 5000,
  })

  async function handleRevoke(t: WorkerTask) {
    setRevoking(s => new Set(s).add(t.id))
    try {
      const versionId = t.kwargs.version_id ? String(t.kwargs.version_id) : undefined
      await api.admin.revokeWorker(t.id, versionId)
      setTimeout(() => qc.invalidateQueries({ queryKey: ['admin-workers'] }), 800)
    } finally {
      setRevoking(s => { const n = new Set(s); n.delete(t.id); return n })
    }
  }

  const tasks = data?.tasks ?? []
  const { paged: pagedTasks, page, setPage, pageSize, setPageSize, total } = usePagedTable(tasks, 'workers')

  return (
    <div>
      <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg)' }}>
              {['Task', 'Ontology', 'Worker', 'State', 'Running', ''].map(h => (
                <th key={h} style={{ padding: '7px 10px', textAlign: h === 'Task' || h === 'Ontology' || h === 'Worker' ? 'left' : 'center', color: 'var(--text-dim)', fontWeight: 500, fontSize: 10, textTransform: 'uppercase', letterSpacing: .5 }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pagedTasks.map(t => (
              <tr key={t.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                <td style={{ padding: '6px 10px' }}>
                  <div style={{ color: JOB_TYPE_COLOR[taskLabel(t.name)] ?? '#79c0ff', fontSize: 10, textTransform: 'uppercase', fontWeight: 600 }}>
                    {taskLabel(t.name)}
                  </div>
                  <div style={{ color: 'var(--text-dim)', fontFamily: 'monospace', fontSize: 9, marginTop: 1 }} title={t.id}>
                    {t.id.slice(0, 8)}…
                  </div>
                </td>
                <td style={{ padding: '6px 10px', color: 'var(--text-dim)', fontSize: 11 }}>
                  {taskDetail(t, versionMap)}
                </td>
                <td style={{ padding: '6px 10px', color: 'var(--text-dim)', fontFamily: 'monospace', fontSize: 10 }}>
                  {t.worker === 'queue' ? '—' : t.worker.replace(/^celery@/, '')}
                </td>
                <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                  {t.state === 'active'
                    ? <span style={{ color: '#58a6ff', fontSize: 11 }}>⟳ running</span>
                    : t.state === 'reserved'
                    ? <span style={{ color: '#d29922', fontSize: 11 }}>⏳ next</span>
                    : <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>· queued</span>
                  }
                </td>
                <td style={{ padding: '6px 10px', textAlign: 'center', color: 'var(--text-dim)', fontSize: 11 }}>
                  {t.time_start ? fmtDuration(new Date(t.time_start * 1000).toISOString(), null) : '—'}
                </td>
                <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                  <button
                    onClick={() => handleRevoke(t)}
                    disabled={revoking.has(t.id)}
                    style={{
                      background: 'rgba(248,81,73,0.1)', border: '1px solid rgba(248,81,73,0.3)',
                      borderRadius: 4, color: '#f85149', fontSize: 10, padding: '2px 8px',
                      cursor: revoking.has(t.id) ? 'default' : 'pointer',
                      opacity: revoking.has(t.id) ? 0.5 : 1,
                    }}
                  >
                    {revoking.has(t.id) ? '…' : 'Cancel'}
                  </button>
                </td>
              </tr>
            ))}
            {pagedTasks.length === 0 && (
              <tr>
                <td colSpan={6} style={{ padding: '16px', textAlign: 'center', color: 'var(--text-dim)' }}>
                  {isFetching ? 'Checking workers…' : 'No active or queued tasks'}
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
