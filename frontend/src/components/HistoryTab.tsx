import { useState } from 'react'
import { OntologyVersion } from '../lib/api'
import { compareVersionsDesc, versionPredecessor } from '../lib/versions'
import { useArbitraryDiff, useGenerateNarrative } from '../hooks/useDiff'
import DiffResultView from './DiffResultView'

interface Props {
  ontologyId: string
  shortname: string
  currentVersionId: string
  versions: OntologyVersion[]
}

export default function HistoryTab({ ontologyId, shortname, currentVersionId, versions }: Props) {
  // Version-aware order (newest release first), not ingest order.
  const sorted = [...versions].sort(compareVersionsDesc)
  // Default the "from" to the real predecessor of the current version.
  const defaultFrom = versionPredecessor(versions, currentVersionId)?.id ?? ''

  const [fromVid, setFromVid] = useState(defaultFrom)
  const [toVid, setToVid]     = useState(currentVersionId)

  // Both dropdowns list every version, so the two sides can end up equal
  // (e.g. pick the current version on the left too). A version diffed against
  // itself is empty and the backend never produces a result, so don't fire the
  // diff — show a hint instead.
  const samePair = !!fromVid && fromVid === toVid

  const { data: diff, isLoading } = useArbitraryDiff(
    ontologyId, samePair ? null : (fromVid || null), samePair ? null : (toVid || null)
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
      <div style={{ padding: 14, display: 'flex', alignItems: 'center', gap: 8, fontFamily: 'monospace', fontSize: 11, flexWrap: 'wrap' }}>
        <span style={{ color: 'var(--text-dim)' }}>Compare</span>
        <select
          value={fromVid}
          onChange={e => setFromVid(e.target.value)}
          style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 4, padding: '3px 8px', color: 'var(--text)', fontSize: 11, fontFamily: 'monospace' }}
        >
          {sorted.map(v => (
            <option key={v.id} value={v.id}>{v.version_iri ?? v.id.slice(0, 8)}</option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => { setFromVid(toVid); setToVid(fromVid) }}
          title="Swap from / to"
          aria-label="Swap from and to versions"
          style={{
            background: 'none', border: 'none', color: 'var(--text-dim)',
            cursor: 'pointer', fontSize: 14, lineHeight: 1, padding: '2px 4px',
          }}
        >
          ⇄
        </button>
        <select
          value={toVid}
          onChange={e => setToVid(e.target.value)}
          style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 4, padding: '3px 8px', color: 'var(--text)', fontSize: 11, fontFamily: 'monospace' }}
        >
          {sorted.map(v => (
            <option key={v.id} value={v.id}>{v.version_iri ?? v.id.slice(0, 8)}</option>
          ))}
        </select>
        <button
          onClick={() => generateNarrative()}
          disabled={!isConsecutivePair || !diff?.diff_data || generatingNarrative}
          title={
            !isConsecutivePair
              ? 'Narratives are only available for consecutive version pairs'
              : !diff?.diff_data
                ? 'Waiting for diff to compute'
                : ''
          }
          style={{
            marginLeft: 'auto',
            background: 'var(--bg-secondary)', border: '1px solid var(--border)',
            borderRadius: 4, padding: '4px 12px',
            color: (!isConsecutivePair || !diff?.diff_data) ? 'var(--text-dim)' : 'var(--text)',
            fontSize: 11,
            cursor: generatingNarrative ? 'wait' : ((!isConsecutivePair || !diff?.diff_data) ? 'not-allowed' : 'pointer'),
            opacity: (!isConsecutivePair || !diff?.diff_data) ? 0.6 : 1,
          }}
        >
          {generatingNarrative ? 'Generating…' : 'Generate narrative'}
        </button>
      </div>

      {diff?.narrative && (
        <div style={{ padding: '0 14px 10px 14px', fontSize: 12, color: 'var(--text-dim)', fontStyle: 'italic' }}>
          {diff.narrative}
        </div>
      )}

      {samePair ? (
        <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 12 }}>
          Select two different versions to compare.
        </div>
      ) : diff?.status === 'failed' ? (
        <div style={{
          padding: '0.75rem 1rem', margin: '0 14px 10px 14px',
          color: 'var(--red)', fontSize: 12,
          background: 'rgba(248,81,73,0.08)', border: '1px solid rgba(248,81,73,0.3)',
          borderRadius: 4,
        }}>
          Diff computation failed. The previous attempt did not complete; try selecting different versions.
        </div>
      ) : isLoading || !diff?.diff_data ? (
        <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 12 }}>
          {diff?.status === 'pending' ? 'Computing diff…' : 'Loading…'}
        </div>
      ) : (
        <DiffResultView
          data={diff.diff_data}
          summary={diff.summary}
          variant="version-diff"
          fromShortname={shortname}
          toShortname={shortname}
        />
      )}
    </div>
  )
}
