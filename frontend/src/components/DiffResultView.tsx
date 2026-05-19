import { useState, useMemo } from 'react'
import { DiffEntity, DiffEntityType, DiffSummary } from '../lib/api'
import ManchesterFrame from './ManchesterFrame'

type Op = 'added' | 'removed' | 'modified'
type ChangeFilter = 'all' | 'literal' | 'axiom'

const ENTITY_TYPE_LABELS: Record<DiffEntityType, string> = {
  class: 'Class',
  object_property: 'Obj. property',
  data_property: 'Data property',
  annotation_property: 'Ann. property',
  individual: 'Individual',
}

interface Props {
  data: {
    added: DiffEntity[]
    removed: DiffEntity[]
    modified: DiffEntity[]
  }
  summary?: DiffSummary
  variant: 'version-diff' | 'cross-compare'
  fromLabel?: string  // for cross-compare bucket headers
  toLabel?: string
  fromShortname?: string | null
  toShortname?: string | null
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
  entity, op, search, expanded, onToggle, variant, fromLabel, toLabel,
  fromShortname, toShortname,
}: {
  entity: DiffEntity & { op: Op }
  op: Op
  search: string
  expanded: boolean
  onToggle: () => void
  variant: 'version-diff' | 'cross-compare'
  fromLabel?: string
  toLabel?: string
  fromShortname: string | null
  toShortname: string | null
}) {
  const opColor = op === 'added' ? 'var(--green, #3fb950)'
    : op === 'removed' ? 'var(--red, #f85149)' : 'var(--orange, #f0883e)'
  const label = entity.label ?? entity.iri.split(/[#/]/).pop() ?? entity.iri
  const opSign = op === 'added' ? '+' : op === 'removed' ? '−' : '~'

  const opTextVersion =
    op === 'added' ? 'added' :
    op === 'removed' ? 'removed' :
    'modified'
  const opTextCross =
    op === 'added' ? `only in ${toLabel ?? 'B'}` :
    op === 'removed' ? `only in ${fromLabel ?? 'A'}` :
    'shared, axioms differ'
  const opLabel = variant === 'cross-compare' ? opTextCross : opTextVersion

  // Added/removed entities ship only {iri, label, entity_type} — guard against
  // missing literal/axiom arrays so the row still renders.
  const literalChanges = entity.literal_changes ?? []
  const hasLiteral = literalChanges.length > 0

  return (
    <div style={{ borderBottom: '1px solid var(--border)' }}>
      <div
        onClick={onToggle}
        style={{
          padding: '6px 10px', cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: 8,
        }}
      >
        <span style={{ color: opColor, fontWeight: 'bold', minWidth: 12 }}>{opSign}</span>
        <span style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', minWidth: 70 }}>
          {ENTITY_TYPE_LABELS[entity.entity_type]}
        </span>
        <span style={{ color: 'var(--text)', fontSize: 12, flex: 1 }}>
          <HighlightedText text={label} query={search} />
        </span>
        <span style={{ color: opColor, fontSize: 10, fontStyle: 'italic' }}>{opLabel}</span>
      </div>
      {expanded && (
        <div style={{ padding: '4px 10px 10px 30px', display: 'flex', flexDirection: 'column', gap: 6 }}>
          {op === 'modified' && hasLiteral && (
            <div>
              <div style={{ color: '#58a6ff', fontSize: 9, textTransform: 'uppercase', fontWeight: 'bold', marginBottom: 4 }}>Literal changes</div>
              {literalChanges.map((lc, i) => (
                <div key={i} style={{ fontSize: 10, marginBottom: 4 }}>
                  <div style={{ color: 'var(--text-dim)' }}>
                    {lc.predicate}{lc.lang ? ` @${lc.lang}` : ''}
                  </div>
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
              <div style={{ color: '#58a6ff', fontSize: 9, textTransform: 'uppercase', fontWeight: 'bold', marginBottom: 4 }}>
                {op === 'modified' ? 'Axiom changes' : op === 'added' ? 'Added entity' : 'Removed entity'}
              </div>
              <ManchesterFrame
                frame={entity.manchester_frame}
                shortname={
                  op === 'removed'  ? fromShortname :
                  op === 'added'    ? toShortname   :
                                      toShortname   // modified → to-side
                }
              />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function DiffResultView({
  data, summary, variant, fromLabel, toLabel, fromShortname, toShortname,
}: Props) {
  const [ops, setOps]               = useState<Set<Op>>(new Set(['added', 'removed', 'modified']))
  const [typeFilter, setTypeFilter] = useState<DiffEntityType | 'all'>('all')
  const [changeFilter, setChangeFilter] = useState<ChangeFilter>('all')
  const [search, setSearch]         = useState('')
  const [expanded, setExpanded]     = useState<Set<string>>(new Set())

  const toggleOp = (op: Op) => {
    setOps(prev => {
      const next = new Set(prev)
      next.has(op) ? next.delete(op) : next.add(op)
      return next
    })
  }

  const allEntities: (DiffEntity & { op: Op })[] = useMemo(() => {
    const result: (DiffEntity & { op: Op })[] = []
    if (ops.has('added'))    data.added.forEach(e => result.push({ ...e, op: 'added' }))
    if (ops.has('removed'))  data.removed.forEach(e => result.push({ ...e, op: 'removed' }))
    if (ops.has('modified')) data.modified.forEach(e => result.push({ ...e, op: 'modified' }))
    return result
  }, [data, ops])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return allEntities.filter(e => {
      if (typeFilter !== 'all' && e.entity_type !== typeFilter) return false
      if (changeFilter === 'literal' && e.op === 'modified' && !(e.literal_changes ?? []).length) return false
      if (changeFilter === 'axiom'   && e.op === 'modified' && !(e.axiom_changes ?? []).length)   return false
      if (changeFilter !== 'all' && e.op !== 'modified') return false
      if (!q) return true
      const label = (e.label ?? '').toLowerCase()
      const iri   = e.iri.toLowerCase()
      const inLit = (e.literal_changes ?? []).some(lc =>
        lc.removed?.toLowerCase().includes(q) || lc.added?.toLowerCase().includes(q)
      )
      const inAxiom = (e.axiom_changes ?? []).some(ac => ac.axiom.toLowerCase().includes(q))
      return label.includes(q) || iri.includes(q) || inLit || inAxiom
    })
  }, [allEntities, typeFilter, changeFilter, search])

  const opLabels: Record<Op, string> = variant === 'cross-compare'
    ? {
        added: toLabel ? `Only in ${toLabel}` : 'Only in B',
        removed: fromLabel ? `Only in ${fromLabel}` : 'Only in A',
        modified: 'Shared (axioms differ)',
      }
    : { added: 'Added', removed: 'Removed', modified: 'Modified' }

  return (
    <div style={{ padding: 14, fontFamily: 'monospace', fontSize: 11, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        {(['added', 'removed', 'modified'] as Op[]).map(op => (
          <label key={op} style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
            <input type="checkbox" checked={ops.has(op)} onChange={() => toggleOp(op)} />
            <span>{opLabels[op]} ({data[op].length})</span>
          </label>
        ))}
        <span style={{ flex: 1 }} />
        <select
          value={typeFilter}
          onChange={e => setTypeFilter(e.target.value as DiffEntityType | 'all')}
          style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 4, padding: '3px 8px', color: 'var(--text)', fontSize: 11, fontFamily: 'monospace' }}
        >
          <option value="all">All types</option>
          {Object.entries(ENTITY_TYPE_LABELS).map(([k, label]) => (
            <option key={k} value={k}>{label}</option>
          ))}
        </select>
        <select
          value={changeFilter}
          onChange={e => setChangeFilter(e.target.value as ChangeFilter)}
          style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 4, padding: '3px 8px', color: 'var(--text)', fontSize: 11, fontFamily: 'monospace' }}
        >
          <option value="all">All changes</option>
          <option value="literal">Literal changes</option>
          <option value="axiom">Axiom changes</option>
        </select>
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search…"
          style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 4, padding: '3px 8px', color: 'var(--text)', fontSize: 11, fontFamily: 'monospace', minWidth: 180 }}
        />
      </div>

      {summary && (
        <div style={{ color: 'var(--text-dim)', fontSize: 11 }}>
          {summary.added} added, {summary.removed} removed, {summary.modified} modified
          {' '}({summary.literal_changes} literal, {summary.axiom_changes} axiom)
        </div>
      )}

      <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
        {filtered.map(entity => (
          <EntityRow
            key={`${entity.op}-${entity.iri}`}
            entity={entity}
            op={entity.op}
            search={search}
            expanded={expanded.has(`${entity.op}-${entity.iri}`)}
            onToggle={() => {
              setExpanded(prev => {
                const key = `${entity.op}-${entity.iri}`
                const next = new Set(prev)
                next.has(key) ? next.delete(key) : next.add(key)
                return next
              })
            }}
            variant={variant}
            fromLabel={fromLabel}
            toLabel={toLabel}
            fromShortname={fromShortname ?? null}
            toShortname={toShortname ?? null}
          />
        ))}
        {filtered.length === 0 && (
          <div style={{ padding: 16, textAlign: 'center', color: 'var(--text-dim)', fontSize: 11 }}>
            No entities match the current filters.
          </div>
        )}
      </div>
    </div>
  )
}
