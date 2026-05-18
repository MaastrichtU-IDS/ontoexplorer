import { useState } from 'react'
import { OntologyVersion } from '../lib/api'
import { useArbitraryDiff, useGenerateNarrative } from '../hooks/useDiff'
import DiffResultView from './DiffResultView'

interface Props {
  ontologyId: string
  currentVersionId: string
  versions: OntologyVersion[]
}

export default function HistoryTab({ ontologyId, currentVersionId, versions }: Props) {
  const sorted = [...versions].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  )
  const currentIdx = sorted.findIndex(v => v.id === currentVersionId)
  const defaultFrom = currentIdx < sorted.length - 1 ? sorted[currentIdx + 1].id : ''

  const [fromVid, setFromVid] = useState(defaultFrom)
  const [toVid, setToVid]     = useState(currentVersionId)

  const { data: diff, isLoading } = useArbitraryDiff(
    ontologyId, fromVid || null, toVid || null
  )
  const { mutate: generateNarrative, isPending: generatingNarrative } =
    useGenerateNarrative(ontologyId, toVid)

  const toVidIdx = sorted.findIndex(v => v.id === toVid)
  const consecutivePrev = toVidIdx < sorted.length - 1 ? sorted[toVidIdx + 1].id : ''
  const isConsecutivePair = fromVid === consecutivePrev

  if (!fromVid) {
    return (
      <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 12 }}>
        This is the only version — no diff available.
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: 14, display: 'flex', alignItems: 'center', gap: 8, fontFamily: 'monospace', fontSize: 11 }}>
        <span style={{ color: 'var(--text-dim)' }}>Compare</span>
        <select
          value={fromVid}
          onChange={e => setFromVid(e.target.value)}
          style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 4, padding: '3px 8px', color: 'var(--text)', fontSize: 11, fontFamily: 'monospace' }}
        >
          {sorted.filter(v => v.id !== toVid).map(v => (
            <option key={v.id} value={v.id}>{v.version_iri ?? v.id.slice(0, 8)}</option>
          ))}
        </select>
        <span style={{ color: 'var(--text-dim)' }}>→</span>
        <select
          value={toVid}
          onChange={e => setToVid(e.target.value)}
          style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 4, padding: '3px 8px', color: 'var(--text)', fontSize: 11, fontFamily: 'monospace' }}
        >
          {sorted.filter(v => v.id !== fromVid).map(v => (
            <option key={v.id} value={v.id}>{v.version_iri ?? v.id.slice(0, 8)}</option>
          ))}
        </select>
        {isConsecutivePair && diff?.diff_data && (
          <button
            onClick={() => generateNarrative()}
            disabled={generatingNarrative}
            style={{
              marginLeft: 'auto',
              background: 'var(--bg-secondary)', border: '1px solid var(--border)',
              borderRadius: 4, padding: '4px 12px',
              color: 'var(--text)', fontSize: 11, cursor: generatingNarrative ? 'wait' : 'pointer',
            }}
          >
            {generatingNarrative ? 'Generating…' : 'Generate narrative'}
          </button>
        )}
      </div>

      {diff?.narrative && (
        <div style={{ padding: '0 14px 10px 14px', fontSize: 12, color: 'var(--text-dim)', fontStyle: 'italic' }}>
          {diff.narrative}
        </div>
      )}

      {isLoading || !diff?.diff_data ? (
        <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 12 }}>
          {diff?.status === 'pending' ? 'Computing diff…' : 'Loading…'}
        </div>
      ) : (
        <DiffResultView
          data={diff.diff_data}
          summary={diff.summary}
          variant="version-diff"
        />
      )}
    </div>
  )
}
