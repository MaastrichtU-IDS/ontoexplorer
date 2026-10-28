import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api, HeldQueueEntry } from '../../lib/api'

// The stale-review backlog is read by age buckets; 0 = everything currently held.
const AGE_FILTERS: { label: string; days: number }[] = [
  { label: 'All held', days: 0 },
  { label: 'Held > 7 days', days: 7 },
  { label: 'Held > 14 days', days: 14 },
  { label: 'Held > 30 days', days: 30 },
]

function reasonChips(reasons: string[]) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
      {reasons.map((r, i) => (
        <span key={i} style={{
          fontSize: '0.68rem', color: 'var(--orange)', border: '1px solid var(--orange)',
          borderRadius: 'var(--radius-sm)', padding: '1px 6px', whiteSpace: 'nowrap',
        }}>{r}</span>
      ))}
    </div>
  )
}

export function HeldQueuePanel() {
  const qc = useQueryClient()
  const [minAgeDays, setMinAgeDays] = useState(0)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [summary, setSummary] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['admin', 'held-queue', minAgeDays],
    queryFn: () => api.admin.heldVersions(minAgeDays),
  })

  const versions: HeldQueueEntry[] = useMemo(() => data?.versions ?? [], [data])
  const selectableIds = useMemo(() => versions.map(v => v.version_id), [versions])
  const allSelected = selectableIds.length > 0 && selectableIds.every(id => selected.has(id))

  function toggle(id: string) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }
  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set(selectableIds))
  }

  const reevaluate = useMutation({
    mutationFn: (ids: string[]) => api.admin.bulkReevaluate(ids),
    onSuccess: (res) => {
      setErr(null)
      const stillHeld = res.results.filter(r => r.outcome === 'still_held').length
      const skipped = res.results.filter(r => r.outcome === 'skipped' || r.outcome === 'not_found').length
      setSummary(
        `Re-ran ${res.requested}: ${res.published} published` +
        `${stillHeld ? `, ${stillHeld} still held` : ''}` +
        `${skipped ? `, ${skipped} skipped` : ''}.`
      )
      setSelected(new Set())
      qc.invalidateQueries({ queryKey: ['admin', 'held-queue'] })
      qc.invalidateQueries({ queryKey: ['admin', 'overview'] })
      qc.invalidateQueries({ queryKey: ['admin-coverage'] })
    },
    onError: (e) => { setSummary(null); setErr((e as Error)?.message || 'Re-check failed') },
  })

  const selectedIds = Array.from(selected)

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: '0.5rem', flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: '0.9rem', fontWeight: 700, color: 'var(--text)', margin: 0 }}>
          Held for review{data ? ` (${data.total})` : ''}
        </h2>
        <select
          value={minAgeDays}
          onChange={e => { setMinAgeDays(Number(e.target.value)); setSelected(new Set()) }}
          style={{
            background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)',
            borderRadius: 'var(--radius-sm)', padding: '4px 8px', fontSize: 'var(--font-size-sm)',
          }}
        >
          {AGE_FILTERS.map(f => <option key={f.days} value={f.days}>{f.label}</option>)}
        </select>
        <button
          onClick={() => reevaluate.mutate(selectedIds)}
          disabled={selectedIds.length === 0 || reevaluate.isPending}
          title="Re-run the quality gate on the selected versions; those that now pass are published"
          style={{
            padding: '5px 14px', borderRadius: 'var(--radius-sm)', border: 'none',
            background: selectedIds.length ? 'var(--green)' : 'var(--border)',
            color: 'var(--on-accent)', fontWeight: 600, fontSize: 'var(--font-size-sm)',
            cursor: selectedIds.length ? 'pointer' : 'default',
          }}
        >
          {reevaluate.isPending ? 'Re-checking…' : `Re-run gate (${selectedIds.length})`}
        </button>
      </div>

      <p style={{ fontSize: '0.72rem', color: 'var(--text-dim)', margin: '0 0 0.9rem' }}>
        Honest re-check from stored signals — a version is published only if it now passes
        (e.g. after a title fix or an added license). This is not the publish override.
      </p>

      {summary && <p style={{ color: 'var(--green)', fontSize: 'var(--font-size-sm)' }}>{summary}</p>}
      {err && <p style={{ color: 'var(--error)', fontSize: 'var(--font-size-sm)' }}>{err}</p>}
      {isLoading && <p style={{ color: 'var(--text-dim)' }}>Loading…</p>}
      {!isLoading && versions.length === 0 && (
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
          Nothing held{minAgeDays ? ` for more than ${minAgeDays} days` : ''}.
        </p>
      )}

      {versions.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--font-size-sm)' }}>
          <thead>
            <tr style={{ textAlign: 'left', color: 'var(--text-dim)', borderBottom: '1px solid var(--border)' }}>
              <th style={{ padding: '6px 8px', width: 28 }}>
                <input type="checkbox" checked={allSelected} onChange={toggleAll} aria-label="Select all held versions" />
              </th>
              <th style={{ padding: '6px 8px' }}>Ontology</th>
              <th style={{ padding: '6px 8px', whiteSpace: 'nowrap' }}>Held for</th>
              <th style={{ padding: '6px 8px' }}>Triples</th>
              <th style={{ padding: '6px 8px' }}>License</th>
              <th style={{ padding: '6px 8px' }}>Reasons</th>
            </tr>
          </thead>
          <tbody>
            {versions.map(v => (
              <tr key={v.version_id} style={{ borderBottom: '1px solid var(--border)', color: 'var(--text)' }}>
                <td style={{ padding: '6px 8px' }}>
                  <input
                    type="checkbox"
                    checked={selected.has(v.version_id)}
                    onChange={() => toggle(v.version_id)}
                    aria-label={`Select ${v.ontology_title || v.ontology_shortname || v.version_id}`}
                  />
                </td>
                <td style={{ padding: '6px 8px' }}>
                  <Link
                    to={`/ontologies/${v.ontology_shortname || v.ontology_id}`}
                    style={{ color: 'var(--accent)', textDecoration: 'none', fontWeight: 600 }}
                  >
                    {v.ontology_title || v.ontology_shortname || v.ontology_id}
                  </Link>
                  {v.ontology_shortname && v.ontology_title && (
                    <span style={{ color: 'var(--text-dim)' }}> · {v.ontology_shortname}</span>
                  )}
                </td>
                <td style={{ padding: '6px 8px', whiteSpace: 'nowrap', color: (v.age_days ?? 0) >= 14 ? 'var(--orange)' : 'var(--text-dim)' }}>
                  {v.age_days != null ? `${v.age_days}d` : '—'}
                </td>
                <td style={{ padding: '6px 8px', color: 'var(--text-dim)' }}>{v.triple_count ?? '—'}</td>
                <td style={{ padding: '6px 8px', color: 'var(--text-dim)' }}>
                  {v.declared_license
                    ? `${v.declared_license} (declared)`
                    : (v.license || v.license_raw || '—')}
                </td>
                <td style={{ padding: '6px 8px' }}>{reasonChips(v.review_reasons)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
