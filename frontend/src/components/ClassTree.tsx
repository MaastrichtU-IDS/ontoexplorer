import { useState, useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useClassTreeNodes, EntityType } from '../hooks/useClassTree'
import { useInferredTreeNodes } from '../hooks/useInferredTree'
import { Term, api, parseTerm } from '../lib/api'
import SourceBadge from './SourceBadge'

type Mode = 'asserted' | 'inferred'

interface NodeProps {
  ontologyId: string
  versionId: string
  term: Term
  depth: number
  selectedIri: string | null
  focusedIri: string | null
  onSelect: (iri: string) => void
  entityType: EntityType
  mode: Mode
  expandSet: Set<string>
  hideInverse: boolean
  hideObsolete: boolean
  expandSignal: number
  collapseSignal: number
  lang?: string | null
}

function TreeNode({ ontologyId, versionId, term, depth, selectedIri, focusedIri, onSelect, entityType, mode, expandSet, hideInverse, hideObsolete, expandSignal, collapseSignal, lang }: NodeProps) {
  const qc = useQueryClient()
  // Prefetch term detail on hover so the click is served from the in-memory
  // queryCache (or the backend's 5-min Redis response cache, whichever fires
  // first). Same queryKey shape as useTerm.
  function prefetchTerm() {
    qc.prefetchQuery({
      queryKey: ['term', ontologyId, versionId, term.iri, lang ?? null],
      queryFn: async () => parseTerm(await api.ontologies.termDetail(ontologyId, versionId, term.iri, lang ?? undefined)),
      staleTime: 60_000,
    })
  }
  const shouldExpand = expandSet.has(term.iri)
  const [expanded, setExpanded] = useState(shouldExpand)

  // When a new reveal path arrives, force-expand ancestors
  useEffect(() => {
    if (shouldExpand) setExpanded(true)
  }, [shouldExpand])

  // Respond to expand/collapse all signals
  useEffect(() => { if (expandSignal > 0 && term.has_children !== false) setExpanded(true) }, [expandSignal])
  useEffect(() => { if (collapseSignal > 0) setExpanded(false) }, [collapseSignal])

  const asserted = useClassTreeNodes(
    mode === 'asserted' && expanded ? ontologyId : null,
    mode === 'asserted' && expanded ? versionId : null,
    mode === 'asserted' && expanded ? term.iri : null,
    entityType,
    hideInverse,
    hideObsolete,
    lang,
  )
  const inferred = useInferredTreeNodes(
    mode === 'inferred' && expanded ? ontologyId : null,
    mode === 'inferred' && expanded ? versionId : null,
    mode === 'inferred' && expanded ? term.iri : null,
    lang,
    hideObsolete,
  )

  const { data: childData, isLoading } = mode === 'asserted' ? asserted : inferred
  const children: Term[] = (childData as any)?.terms ?? []

  const isSelected = selectedIri === term.iri
  const isFocused = focusedIri === term.iri
  const isUnsat = term.is_unsatisfiable === true
  const isNothing = term.iri === 'http://www.w3.org/2002/07/owl#Nothing'
  const label = term.label ?? term.iri.split(/[#/]/).pop() ?? term.iri
  // has_children undefined means unknown (e.g. root before first load) — show toggle optimistically
  const canExpand = term.has_children !== false

  function handleToggle(e: React.MouseEvent) {
    e.stopPropagation()
    setExpanded(v => !v)
  }

  // Protégé-style: unsat classes render in red. The synthetic owl:Nothing node
  // gets a softer red (orange-ish) so users can distinguish "this is the holding
  // pen for unsat classes" from "this class is itself unsatisfiable".
  const unsatColor = isNothing ? 'var(--od-yellow)' : 'var(--error)'
  const nodeColor = isSelected
    ? 'var(--accent)'
    : (isUnsat || isNothing ? unsatColor : 'var(--text)')

  const tooltip = isUnsat
    ? 'Unsatisfiable'
    : isNothing
      ? `owl:Nothing — synthetic root for ${term.unsat_children_count ?? 0} unsatisfiable class(es)`
      : undefined

  return (
    <li>
      <div
        data-iri={term.iri}
        data-expandable={canExpand ? 'true' : 'false'}
        data-expanded={expanded ? 'true' : 'false'}
        onClick={() => onSelect(term.iri)}
        title={tooltip}
        style={{
          display: 'flex', alignItems: 'center', gap: 4,
          padding: `4px 8px 4px ${8 + depth * 12}px`,
          cursor: 'pointer',
          background: isSelected ? 'var(--bg-hover)' : 'transparent',
          borderRadius: 'var(--radius-sm)',
          color: nodeColor,
          fontWeight: isNothing ? 600 : undefined,
          outline: isFocused && !isSelected ? '1px solid var(--accent)' : 'none',
          outlineOffset: -1,
        }}
        onMouseEnter={e => {
          if (!isSelected) e.currentTarget.style.background = 'var(--overlay)'
          prefetchTerm()
        }}
        onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = '' }}
      >
        <span
          data-toggle="true"
          onClick={canExpand ? handleToggle : undefined}
          style={{ width: 14, fontSize: 10, color: 'var(--text-dim)', flexShrink: 0, userSelect: 'none',
            cursor: canExpand ? 'pointer' : 'default' }}
        >
          {canExpand ? (isLoading ? '…' : expanded ? '▾' : '▸') : ''}
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4, flex: 1, overflow: 'hidden', minWidth: 0 }}>
          <span style={{ fontSize: 'var(--font-size-sm)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {label}
            {isNothing && term.unsat_children_count != null && (
              <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--text-dim)' }}>
                ({term.unsat_children_count})
              </span>
            )}
          </span>
          {term.lang && (
            <span style={{
              fontSize: 9, padding: '1px 4px', borderRadius: 3, flexShrink: 0,
              background: 'var(--bg)', border: '1px solid var(--border)',
              color: 'var(--text-dim)', fontFamily: 'monospace',
            }}>
              {term.lang}
            </span>
          )}
        </span>
        {term.source && <SourceBadge source={term.source} />}
      </div>
      {expanded && children.length > 0 && (
        <ul style={{ listStyle: 'none' }}>
          {children.map(child => (
            <TreeNode
              key={child.iri}
              ontologyId={ontologyId}
              versionId={versionId}
              term={child}
              depth={depth + 1}
              selectedIri={selectedIri}
              focusedIri={focusedIri}
              onSelect={onSelect}
              entityType={entityType}
              mode={mode}
              expandSet={expandSet}
              hideInverse={hideInverse}
              hideObsolete={hideObsolete}
              expandSignal={expandSignal}
              collapseSignal={collapseSignal}
              lang={lang}
            />
          ))}
        </ul>
      )}
    </li>
  )
}

interface Props {
  ontologyId: string
  versionId: string
  selectedIri: string | null
  onSelect: (iri: string) => void
  entityType?: EntityType
  mode?: Mode
  revealIri?: string | null
  hideInverse?: boolean
  hideObsolete?: boolean
  expandSignal?: number
  collapseSignal?: number
  lang?: string | null
}

const EMPTY_SET = new Set<string>()

export default function ClassTree({ ontologyId, versionId, selectedIri, onSelect, entityType = 'class', mode = 'asserted', revealIri, hideInverse = false, hideObsolete = true, expandSignal = 0, collapseSignal = 0, lang }: Props) {
  const asserted = useClassTreeNodes(mode === 'asserted' ? ontologyId : null, mode === 'asserted' ? versionId : null, null, entityType, hideInverse, hideObsolete, lang)
  const inferred = useInferredTreeNodes(mode === 'inferred' ? ontologyId : null, mode === 'inferred' ? versionId : null, null, lang, hideObsolete)

  const { data, isLoading } = mode === 'asserted' ? asserted : inferred
  const roots: Term[] = (data as any)?.terms ?? []
  const reasoningAvailable = mode === 'inferred' ? (data as any)?.reasoning_available !== false : true

  const { data: ancestorData } = useQuery({
    queryKey: ['ancestors', ontologyId, versionId, revealIri, mode],
    queryFn: () => api.ontologies.ancestors(ontologyId, versionId, revealIri!, mode),
    enabled: !!revealIri,
    staleTime: 120_000,
  })

  const expandSet: Set<string> = ancestorData?.ancestors
    ? new Set(ancestorData.ancestors.map((a: Term) => a.iri))
    : EMPTY_SET

  // After ancestors load (which drives expansion), scroll the selected node into view.
  // We use a MutationObserver rather than a fixed timeout because deep hierarchies require
  // multiple cascading async fetches (one per level) before the target node exists in the DOM.
  const containerRef = useRef<HTMLUListElement>(null)
  useEffect(() => {
    if (!revealIri || ancestorData === undefined) return
    const container = containerRef.current
    if (!container) return

    const escaped = CSS.escape(revealIri)
    const scrollTo = (el: HTMLElement) => el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })

    // Already in DOM (e.g. shallow tree or cached expansion)
    const existing = container.querySelector(`[data-iri="${escaped}"]`) as HTMLElement | null
    if (existing) {
      scrollTo(existing)
      return
    }

    // Watch for the node to appear as the tree expands level by level
    const observer = new MutationObserver(() => {
      const el = container.querySelector(`[data-iri="${escaped}"]`) as HTMLElement | null
      if (el) {
        observer.disconnect()
        clearTimeout(giveUp)
        scrollTo(el)
      }
    })
    observer.observe(container, { childList: true, subtree: true })

    // Give up after 5s to avoid leaking the observer on broken trees
    const giveUp = setTimeout(() => observer.disconnect(), 5000)
    return () => { observer.disconnect(); clearTimeout(giveUp) }
  }, [revealIri, ancestorData])

  const [focusedIri, setFocusedIri] = useState<string | null>(null)

  function handleKeyDown(e: React.KeyboardEvent) {
    const container = containerRef.current
    if (!container) return

    const navKeys = ['ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft', 'Enter']
    if (!navKeys.includes(e.key)) return
    e.preventDefault()

    const visible = Array.from(container.querySelectorAll('[data-iri]'))
      .map(el => (el as HTMLElement).dataset.iri!)
      .filter(Boolean)
    if (visible.length === 0) return

    const currentIri = focusedIri ?? selectedIri
    const idx = currentIri ? visible.indexOf(currentIri) : -1

    if (e.key === 'ArrowDown') {
      const next = idx === -1 ? visible[0] : visible[Math.min(idx + 1, visible.length - 1)]
      setFocusedIri(next)
      ;(container.querySelector(`[data-iri="${CSS.escape(next)}"]`) as HTMLElement | null)
        ?.scrollIntoView({ block: 'nearest' })
      return
    }

    if (e.key === 'ArrowUp') {
      const prev = idx === -1 ? visible[visible.length - 1] : visible[Math.max(idx - 1, 0)]
      setFocusedIri(prev)
      ;(container.querySelector(`[data-iri="${CSS.escape(prev)}"]`) as HTMLElement | null)
        ?.scrollIntoView({ block: 'nearest' })
      return
    }

    if (!currentIri) return
    const nodeDiv = container.querySelector(`[data-iri="${CSS.escape(currentIri)}"]`) as HTMLElement | null
    if (!nodeDiv) return

    if (e.key === 'ArrowRight') {
      if (nodeDiv.dataset.expandable === 'true' && nodeDiv.dataset.expanded === 'false') {
        ;(nodeDiv.querySelector('[data-toggle]') as HTMLElement | null)?.click()
      }
      return
    }

    if (e.key === 'ArrowLeft') {
      if (nodeDiv.dataset.expandable === 'true' && nodeDiv.dataset.expanded === 'true') {
        ;(nodeDiv.querySelector('[data-toggle]') as HTMLElement | null)?.click()
      }
      return
    }

    if (e.key === 'Enter') {
      onSelect(currentIri)
    }
  }

  if (isLoading) {
    return <div style={{ padding: '0.5rem 1rem', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>Loading…</div>
  }

  if (mode === 'inferred' && !isLoading && !reasoningAvailable) {
    return (
      <div style={{ padding: '0.5rem 1rem', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', fontStyle: 'italic' }}>
        Reasoning not yet complete for this version.
      </div>
    )
  }

  if (roots.length === 0) {
    const label = entityType === 'class' ? 'classes'
      : entityType === 'object_property' ? 'object properties'
      : entityType === 'data_property' ? 'data properties'
      : entityType === 'annotation_property' ? 'annotation properties'
      : 'properties'
    return <div style={{ padding: '0.5rem 1rem', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
      No {label} found
    </div>
  }

  return (
    <div tabIndex={0} onKeyDown={handleKeyDown} style={{ outline: 'none' }}>
      <ul ref={containerRef} style={{ listStyle: 'none' }}>
        {roots.map(term => (
          <TreeNode
            key={term.iri}
            ontologyId={ontologyId}
            versionId={versionId}
            term={term}
            depth={0}
            selectedIri={selectedIri}
            focusedIri={focusedIri}
            onSelect={onSelect}
            entityType={entityType}
            mode={mode}
            expandSet={expandSet}
            hideInverse={hideInverse}
            hideObsolete={hideObsolete}
            expandSignal={expandSignal}
            collapseSignal={collapseSignal}
            lang={lang}
          />
        ))}
      </ul>
    </div>
  )
}
