import { useState, useMemo, useEffect, useRef, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { DiffEntity, DiffEntityType, DiffSummary } from '../lib/api'
import ManchesterFrame from './ManchesterFrame'

type Op = 'added' | 'removed' | 'modified'
type ChangeFilter = 'all' | 'literal' | 'axiom'

const ALL_OPS: readonly Op[] = ['added', 'removed', 'modified'] as const
const ENTITY_TYPE_KEYS: readonly DiffEntityType[] = [
  'class', 'object_property', 'data_property', 'annotation_property', 'individual',
]

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

/**
 * URL-persisted state for the diff view. Filter/expand bits round-trip
 * through `df_*` search params so back-button and link-sharing restore the
 * view. Discrete user actions (toggling op visibility, changing a filter,
 * expanding a row) PUSH a new history entry so the back button traverses
 * them. The search input debounces to ~200 ms and uses replace so each
 * keystroke isn't a separate history entry.
 *
 * All updates use functional setSearchParams to preserve parent-route
 * params (e.g. tab=history, from=..., to=...).
 */
function useDiffViewURLState() {
  const [searchParams, setSearchParams] = useSearchParams()

  // Derive filters from URL via useMemo so we don't keep a stale local mirror.
  const ops = useMemo<Set<Op>>(() => {
    const raw = searchParams.get('df_ops')
    if (!raw) return new Set(ALL_OPS)
    const parts = raw.split(',').filter((p): p is Op =>
      p === 'added' || p === 'removed' || p === 'modified',
    )
    return new Set(parts)
  }, [searchParams])

  const typeFilter = useMemo<DiffEntityType | 'all'>(() => {
    const raw = searchParams.get('df_type')
    if (!raw) return 'all'
    return (ENTITY_TYPE_KEYS as readonly string[]).includes(raw)
      ? (raw as DiffEntityType)
      : 'all'
  }, [searchParams])

  const changeFilter = useMemo<ChangeFilter>(() => {
    const raw = searchParams.get('df_cf')
    return raw === 'literal' || raw === 'axiom' ? raw : 'all'
  }, [searchParams])

  const expanded = useMemo<Set<string>>(() => {
    const raw = searchParams.get('df_e')
    if (!raw) return new Set()
    return new Set(raw.split(',').filter(Boolean).map(decodeURIComponent))
  }, [searchParams])

  // Search: local state mirrors URL on mount, then debounces writes back.
  const [search, setSearchLocal] = useState<string>(() => searchParams.get('df_q') ?? '')
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const setSearch = useCallback((next: string) => {
    setSearchLocal(next)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setSearchParams(prev => {
        if (next) prev.set('df_q', next)
        else prev.delete('df_q')
        return prev
      }, { replace: true })
    }, 200)
  }, [setSearchParams])

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [])

  const setOps = useCallback((next: Set<Op>) => {
    setSearchParams(prev => {
      const allSelected = ALL_OPS.every(op => next.has(op))
      if (allSelected) {
        // Default — don't serialize.
        prev.delete('df_ops')
      } else {
        // Preserve canonical order so URL is stable across toggles.
        const ordered = ALL_OPS.filter(op => next.has(op))
        prev.set('df_ops', ordered.join(','))
      }
      return prev
    })
  }, [setSearchParams])

  const setTypeFilter = useCallback((next: DiffEntityType | 'all') => {
    setSearchParams(prev => {
      if (next === 'all') prev.delete('df_type')
      else prev.set('df_type', next)
      return prev
    })
  }, [setSearchParams])

  const setChangeFilter = useCallback((next: ChangeFilter) => {
    setSearchParams(prev => {
      if (next === 'all') prev.delete('df_cf')
      else prev.set('df_cf', next)
      return prev
    })
  }, [setSearchParams])

  const toggleExpanded = useCallback((iri: string) => {
    setSearchParams(prev => {
      const raw = prev.get('df_e')
      const current = new Set(
        raw ? raw.split(',').filter(Boolean).map(decodeURIComponent) : [],
      )
      if (current.has(iri)) current.delete(iri)
      else current.add(iri)
      if (current.size === 0) {
        prev.delete('df_e')
      } else {
        prev.set('df_e', Array.from(current).map(encodeURIComponent).join(','))
      }
      return prev
    })
  }, [setSearchParams])

  return {
    ops, setOps,
    typeFilter, setTypeFilter,
    changeFilter, setChangeFilter,
    expanded, toggleExpanded,
    search, setSearch,
  }
}

function InferredUnavailableNotice({
  status,
}: {
  status: DiffSummary['inferred_status'] | undefined
}) {
  const [dismissed, setDismissed] = useState(false)
  if (!status) return null
  if (status.from_version === 'ready' && status.to_version === 'ready') return null
  if (dismissed) return null
  const badSide = status.from_version !== 'ready' ? 'from_version' : 'to_version'
  const badStatus = status[badSide]
  return (
    <div
      style={{
        background: 'var(--bg-tertiary)',
        border: '1px solid var(--border)',
        borderRadius: 4,
        padding: '8px 12px',
        fontSize: 11,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
      }}
    >
      <span style={{ color: 'var(--blue)' }}>ⓘ</span>
      <span style={{ flex: 1 }}>
        Inferred diff unavailable: reasoning is {badStatus} for {badSide}. The
        diff will refresh automatically when reasoning completes.
      </span>
      <button
        onClick={() => setDismissed(true)}
        style={{
          background: 'none',
          border: 'none',
          color: 'var(--text-dim)',
          cursor: 'pointer',
        }}
        aria-label="Dismiss"
      >
        ×
      </button>
    </div>
  )
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
  const opColor = op === 'added' ? 'var(--green)'
    : op === 'removed' ? 'var(--red)' : 'var(--orange)'
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
              <div style={{ color: 'var(--blue)', fontSize: 9, textTransform: 'uppercase', fontWeight: 'bold', marginBottom: 4 }}>Literal changes</div>
              {literalChanges.map((lc, i) => (
                <div key={i} style={{ fontSize: 10, marginBottom: 4, wordBreak: 'break-word' }}>
                  <div style={{ color: 'var(--text-dim)' }}>
                    {lc.predicate}{lc.lang ? ` @${lc.lang}` : ''}
                  </div>
                  <div>
                    {lc.removed != null && (
                      <div>
                        <HighlightedText text={`− "${lc.removed}"`} query={search} color="var(--red)" />
                      </div>
                    )}
                    {lc.added != null && (
                      <div>
                        <HighlightedText text={`+ "${lc.added}"`} query={search} color="var(--green)" />
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
          {entity.manchester_frame && (
            <div style={{ marginTop: 6 }}>
              <div style={{ color: 'var(--blue)', fontSize: 9, textTransform: 'uppercase', fontWeight: 'bold', marginBottom: 4 }}>
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
  const {
    ops, setOps,
    typeFilter, setTypeFilter,
    changeFilter, setChangeFilter,
    expanded, toggleExpanded,
    search, setSearch,
  } = useDiffViewURLState()

  const toggleOp = (op: Op) => {
    const next = new Set(ops)
    if (next.has(op)) next.delete(op)
    else next.add(op)
    setOps(next)
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
      {summary && <InferredUnavailableNotice status={summary.inferred_status} />}
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
          {' '}({summary.literal_changes} literal, {summary.axiom_changes} axiom
          {summary.asserted_axiom_changes != null && summary.inferred_axiom_changes != null && (
            <> — {summary.asserted_axiom_changes} asserted, {summary.inferred_axiom_changes} inferred</>
          )}
          )
        </div>
      )}

      <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
        {filtered.map(entity => (
          <EntityRow
            key={entity.iri}
            entity={entity}
            op={entity.op}
            search={search}
            expanded={expanded.has(entity.iri)}
            onToggle={() => toggleExpanded(entity.iri)}
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
