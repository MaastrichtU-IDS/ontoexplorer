import { useState, useMemo } from 'react'
import { OntologyVersion, DiffEntity, DiffEntityType } from '../lib/api'
import { useArbitraryDiff, useGenerateNarrative } from '../hooks/useDiff'
import ManchesterFrame from './ManchesterFrame'

type Op = 'added' | 'removed' | 'modified'
type ChangeFilter = 'all' | 'literal' | 'axiom'

interface Props {
  ontologyId: string
  currentVersionId: string
  versions: OntologyVersion[]
}

const ENTITY_TYPE_LABELS: Record<DiffEntityType, string> = {
  class: 'Class',
  object_property: 'Obj. property',
  data_property: 'Data property',
  annotation_property: 'Ann. property',
  individual: 'Individual',
}

function HighlightedText({ text, query, color }: { text: string; query: string; color?: string }) {
  if (!query) return <span style={{ color }}>{text}</span>
  const lower = text.toLowerCase()
  const lowerQ = query.toLowerCase()
  const idx = lower.indexOf(lowerQ)
  if (idx === -1) return <span style={{ color }}>{text}</span>
  return (
    <span style={{ color }}>
      {text.slice(0, idx)}
      <mark style={{ background: 'rgba(247,185,62,0.25)', color: 'inherit', borderRadius: 2 }}>
        {text.slice(idx, idx + query.length)}
      </mark>
      {text.slice(idx + query.length)}
    </span>
  )
}

function EntityRow({
  entity, op, search, expanded, onToggle,
}: {
  entity: DiffEntity & { op: Op }
  op: Op
  search: string
  expanded: boolean
  onToggle: () => void
}) {
  const opColor = op === 'added' ? 'var(--green, #3fb950)'
    : op === 'removed' ? 'var(--red, #f85149)' : 'var(--orange, #f0883e)'
  const label = entity.label ?? entity.iri.split(/[#/]/).pop() ?? entity.iri

  const hasLiteral = entity.literal_changes.length > 0
  const hasAxiom   = entity.axiom_changes.length > 0

  return (
    <div style={{ border: `1px solid ${opColor}`, borderRadius: 5, overflow: 'hidden', fontSize: 11, fontFamily: 'monospace' }}>
      <div
        onClick={op === 'modified' ? onToggle : undefined}
        style={{
          padding: '7px 12px', display: 'flex', alignItems: 'center', gap: 6,
          cursor: op === 'modified' ? 'pointer' : 'default',
          borderBottom: expanded ? '1px solid var(--border, #30363d)' : 'none',
          background: 'var(--bg-secondary, #161b22)',
        }}
      >
        {op === 'modified' && (
          <span style={{ color: opColor, fontSize: 10 }}>{expanded ? '▾' : '▸'}</span>
        )}
        <span style={{ color: opColor, fontWeight: 'bold', width: 12 }}>
          {op === 'added' ? '+' : op === 'removed' ? '−' : '~'}
        </span>
        <span style={{ color: 'var(--text, #e6edf3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
          <HighlightedText text={label} query={search} />
        </span>
        <span style={{ color: 'var(--text-dim, #8b949e)', fontSize: 10, flexShrink: 0 }}>
          {ENTITY_TYPE_LABELS[entity.entity_type]}
        </span>
        {op === 'modified' && (
          <span style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
            {hasLiteral && (
              <span style={{ border: '1px solid #a371f7', borderRadius: 3, padding: '1px 6px', fontSize: 9, color: '#a371f7' }}>literal</span>
            )}
            {hasAxiom && (
              <span style={{ border: '1px solid #58a6ff', borderRadius: 3, padding: '1px 6px', fontSize: 9, color: '#58a6ff' }}>axiom</span>
            )}
          </span>
        )}
      </div>

      {expanded && op === 'modified' && (
        <div style={{ padding: '8px 16px', display: 'flex', flexDirection: 'column', gap: 8, background: 'var(--bg, #0d1117)' }}>
          {hasLiteral && (
            <div>
              <div style={{ color: '#a371f7', fontSize: 9, textTransform: 'uppercase', fontWeight: 'bold', marginBottom: 4 }}>Literal changes</div>
              {entity.literal_changes.map((lc, i) => (
                <div key={i} style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: 4, marginBottom: 3 }}>
                  <span style={{ color: 'var(--text-dim, #8b949e)', fontSize: 10, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {lc.predicate.split(/[#/]/).pop()}{lc.lang ? ` [${lc.lang}]` : ''}
                  </span>
                  <div>
                    {lc.removed != null && (
                      <div>
                        <HighlightedText text={`− "${lc.removed}"`} query={search} color="#f85149" />
                      </div>
                    )}
                    {lc.added != null && (
                      <div>
                        <HighlightedText text={`+ "${lc.added}"`} query={search} color="#3fb950" />
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {entity.manchester_frame && (
            <div style={{ marginTop: 6 }}>
              <div style={{ color: '#58a6ff', fontSize: 9, textTransform: 'uppercase', fontWeight: 'bold', marginBottom: 4 }}>Axiom changes</div>
              <ManchesterFrame frame={entity.manchester_frame} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function HistoryTab({ ontologyId, currentVersionId, versions }: Props) {
  const sorted = [...versions].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  )
  const currentIdx = sorted.findIndex(v => v.id === currentVersionId)
  const defaultFrom = currentIdx < sorted.length - 1 ? sorted[currentIdx + 1].id : ''

  const [fromVid, setFromVid] = useState(defaultFrom)
  const [toVid, setToVid]     = useState(currentVersionId)
  const [ops, setOps]         = useState<Set<Op>>(new Set(['added', 'removed', 'modified']))
  const [typeFilter, setTypeFilter] = useState<DiffEntityType | 'all'>('all')
  const [changeFilter, setChangeFilter] = useState<ChangeFilter>('all')
  const [search, setSearch]   = useState('')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const { data: diff, isLoading } = useArbitraryDiff(
    ontologyId, fromVid || null, toVid || null
  )
  const { mutate: generateNarrative, isPending: generatingNarrative } =
    useGenerateNarrative(ontologyId, toVid)

  // Narrative endpoint only supports consecutive diffs (prev → toVid).
  // Disable the button when the user has selected a non-consecutive pair.
  const toVidIdx = sorted.findIndex(v => v.id === toVid)
  const consecutivePrev = toVidIdx < sorted.length - 1 ? sorted[toVidIdx + 1].id : ''
  const isConsecutivePair = fromVid === consecutivePrev

  const toggleOp = (op: Op) => {
    setOps(prev => {
      const next = new Set(prev)
      next.has(op) ? next.delete(op) : next.add(op)
      return next
    })
  }

  const allEntities: (DiffEntity & { op: Op })[] = useMemo(() => {
    if (!diff?.diff_data) return []
    const result: (DiffEntity & { op: Op })[] = []
    if (ops.has('added'))    diff.diff_data.added.forEach(e => result.push({ ...e, op: 'added' }))
    if (ops.has('removed'))  diff.diff_data.removed.forEach(e => result.push({ ...e, op: 'removed' }))
    if (ops.has('modified')) diff.diff_data.modified.forEach(e => result.push({ ...e, op: 'modified' }))
    return result
  }, [diff, ops])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return allEntities.filter(e => {
      if (typeFilter !== 'all' && e.entity_type !== typeFilter) return false
      if (changeFilter === 'literal' && e.op === 'modified' && !e.literal_changes.length) return false
      if (changeFilter === 'axiom'   && e.op === 'modified' && !e.axiom_changes.length)   return false
      if (changeFilter !== 'all' && e.op !== 'modified') return false
      if (!q) return true
      const label = (e.label ?? '').toLowerCase()
      const iri   = e.iri.toLowerCase()
      const inLit = e.literal_changes.some(lc =>
        lc.removed?.toLowerCase().includes(q) || lc.added?.toLowerCase().includes(q)
      )
      const inAxiom = e.axiom_changes.some(ac => ac.axiom.toLowerCase().includes(q))
      return label.includes(q) || iri.includes(q) || inLit || inAxiom
    })
  }, [allEntities, typeFilter, changeFilter, search])

  if (!fromVid) {
    return (
      <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 12 }}>
        This is the only version — no diff available.
      </div>
    )
  }

  const summary = diff?.diff_data
    ? {
        added:    diff.diff_data.added.length,
        removed:  diff.diff_data.removed.length,
        modified: diff.diff_data.modified.length,
      }
    : null

  return (
    <div style={{ padding: 14, fontFamily: 'monospace', fontSize: 11, display: 'flex', flexDirection: 'column', gap: 10 }}>
      {/* Version picker */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
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
            <option key={v.id} value={v.id}>
              {v.version_iri ?? v.id.slice(0, 8)}{v.id === currentVersionId ? ' (current)' : ''}
            </option>
          ))}
        </select>
        <button
          onClick={() => generateNarrative()}
          disabled={!diff || diff.status !== 'ready' || generatingNarrative || !isConsecutivePair}
          title={!isConsecutivePair ? 'Changelog generation is only available for consecutive version pairs' : undefined}
          style={{
            marginLeft: 'auto', background: '#238636', color: '#fff', border: 'none',
            borderRadius: 4, padding: '3px 10px', cursor: isConsecutivePair ? 'pointer' : 'not-allowed', fontSize: 10,
            opacity: (!diff || diff.status !== 'ready' || !isConsecutivePair) ? 0.5 : 1,
          }}
        >
          {generatingNarrative ? 'Generating…' : 'Generate changelog'}
        </button>
      </div>

      {/* Loading / pending states */}
      {isLoading && (
        <div style={{ color: 'var(--text-dim)' }}>Loading diff…</div>
      )}
      {diff?.status === 'pending' && (
        <div style={{ color: 'var(--text-dim)' }}>Computing diff… (polling every 3 s)</div>
      )}
      {diff?.status === 'failed' && (
        <div style={{ color: '#f85149' }}>Diff computation failed.</div>
      )}

      {diff?.status === 'ready' && summary && (<>
        {/* Operation toggles */}
        <div style={{ display: 'flex', gap: 8 }}>
          {(['added', 'removed', 'modified'] as Op[]).map(op => {
            const count = op === 'added' ? summary.added : op === 'removed' ? summary.removed : summary.modified
            const color = op === 'added' ? '#3fb950' : op === 'removed' ? '#f85149' : '#f0883e'
            const active = ops.has(op)
            return (
              <button
                key={op}
                onClick={() => toggleOp(op)}
                style={{
                  background: active ? `${color}22` : 'var(--bg-secondary)',
                  border: `1px solid ${active ? color : 'var(--border)'}`,
                  borderRadius: 6, padding: '6px 14px', cursor: 'pointer', minWidth: 70,
                  opacity: active ? 1 : 0.4,
                }}
              >
                <div style={{ color, fontSize: 15, fontWeight: 'bold' }}>{count}</div>
                <div style={{ color, fontSize: 10 }}>{op === 'added' ? '+ added' : op === 'removed' ? '− removed' : '~ modified'}</div>
              </button>
            )
          })}
        </div>

        {/* Entity type filter */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
          <span style={{ color: 'var(--text-dim)', marginRight: 4 }}>Type:</span>
          {(['all', 'class', 'object_property', 'data_property', 'annotation_property', 'individual'] as const).map(t => (
            <button
              key={t}
              onClick={() => setTypeFilter(t)}
              style={{
                background: typeFilter === t ? 'var(--accent, #1f6feb)' : 'var(--bg-secondary)',
                color: typeFilter === t ? '#fff' : 'var(--text-dim)',
                border: `1px solid ${typeFilter === t ? 'var(--accent)' : 'var(--border)'}`,
                borderRadius: 10, padding: '2px 10px', cursor: 'pointer', fontSize: 10,
              }}
            >
              {t === 'all' ? 'All' : ENTITY_TYPE_LABELS[t as DiffEntityType]}
            </button>
          ))}
        </div>

        {/* Change type filter */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ color: 'var(--text-dim)', marginRight: 4 }}>Changes:</span>
          {(['all', 'literal', 'axiom'] as ChangeFilter[]).map(cf => (
            <button
              key={cf}
              onClick={() => setChangeFilter(cf)}
              style={{
                background: changeFilter === cf ? 'var(--accent)' : 'var(--bg-secondary)',
                color: changeFilter === cf ? '#fff' : 'var(--text-dim)',
                border: `1px solid ${changeFilter === cf ? 'var(--accent)' : 'var(--border)'}`,
                borderRadius: 10, padding: '2px 10px', cursor: 'pointer', fontSize: 10,
              }}
            >
              {cf === 'all' ? 'All' : cf.charAt(0).toUpperCase() + cf.slice(1)}
            </button>
          ))}
        </div>

        {/* Keyword search */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search label, IRI, or changed value…"
            style={{
              flex: 1, background: 'var(--bg)', border: `1px solid ${search ? 'var(--accent)' : 'var(--border)'}`,
              borderRadius: 4, padding: '5px 10px', color: 'var(--text)', fontSize: 11, fontFamily: 'monospace',
            }}
          />
          {search && (
            <button onClick={() => setSearch('')} style={{ background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer', fontSize: 12 }}>✕</button>
          )}
        </div>

        {/* Result count */}
        <div style={{ color: 'var(--text-dim)', fontSize: 10 }}>
          Showing {filtered.length} of {summary.added + summary.removed + summary.modified} entities
          {search && <span> matching <span style={{ color: 'var(--accent)' }}>"{search}"</span></span>}
        </div>

        {/* LLM narrative */}
        {diff.narrative && (
          <div style={{
            background: 'var(--bg)', border: '1px solid #238636', borderRadius: 6,
            padding: '9px 12px', fontSize: 10, lineHeight: 1.6,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
              <span style={{ color: '#3fb950', fontWeight: 'bold' }}>Changelog</span>
              <button
                onClick={() => navigator.clipboard.writeText(diff.narrative!)}
                style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer', fontSize: 11 }}
                title="Copy to clipboard"
              >
                ⎘
              </button>
            </div>
            <span style={{ color: 'var(--text-dim)', fontStyle: 'italic' }}>{diff.narrative}</span>
          </div>
        )}

        {/* Entity list */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {filtered.map(entity => (
            <EntityRow
              key={`${entity.op}:${entity.iri}`}
              entity={entity}
              op={entity.op}
              search={search}
              expanded={expanded.has(entity.iri)}
              onToggle={() => setExpanded(prev => {
                const next = new Set(prev)
                next.has(entity.iri) ? next.delete(entity.iri) : next.add(entity.iri)
                return next
              })}
            />
          ))}
          {filtered.length === 0 && (
            <div style={{ color: 'var(--text-dim)', padding: '8px 4px' }}>No matching entities.</div>
          )}
        </div>
      </>)}
    </div>
  )
}
