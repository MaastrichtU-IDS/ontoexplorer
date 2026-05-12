import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useClassTreeNodes, EntityType } from '../hooks/useClassTree'
import { useInferredTreeNodes } from '../hooks/useInferredTree'
import { Term, api } from '../lib/api'

type Mode = 'asserted' | 'inferred'

interface NodeProps {
  ontologyId: string
  versionId: string
  term: Term
  depth: number
  selectedIri: string | null
  onSelect: (iri: string) => void
  entityType: EntityType
  mode: Mode
  expandSet: Set<string>
  hideInverse: boolean
}

function TreeNode({ ontologyId, versionId, term, depth, selectedIri, onSelect, entityType, mode, expandSet, hideInverse }: NodeProps) {
  const shouldExpand = expandSet.has(term.iri)
  const [expanded, setExpanded] = useState(shouldExpand)

  // When a new reveal path arrives, force-expand ancestors
  useEffect(() => {
    if (shouldExpand) setExpanded(true)
  }, [shouldExpand])

  const asserted = useClassTreeNodes(
    mode === 'asserted' && expanded ? ontologyId : null,
    mode === 'asserted' && expanded ? versionId : null,
    mode === 'asserted' && expanded ? term.iri : null,
    entityType,
    hideInverse,
  )
  const inferred = useInferredTreeNodes(
    mode === 'inferred' && expanded ? ontologyId : null,
    mode === 'inferred' && expanded ? versionId : null,
    mode === 'inferred' && expanded ? term.iri : null,
  )

  const { data: childData, isLoading } = mode === 'asserted' ? asserted : inferred
  const children: Term[] = (childData as any)?.terms ?? []

  const isSelected = selectedIri === term.iri
  const label = term.label ?? term.iri.split(/[#/]/).pop() ?? term.iri
  // has_children undefined means unknown (e.g. root before first load) — show toggle optimistically
  const canExpand = term.has_children !== false

  function handleToggle(e: React.MouseEvent) {
    e.stopPropagation()
    setExpanded(v => !v)
  }

  return (
    <li>
      <div
        data-iri={term.iri}
        onClick={() => onSelect(term.iri)}
        style={{
          display: 'flex', alignItems: 'center', gap: 4,
          padding: `4px 8px 4px ${8 + depth * 12}px`,
          cursor: 'pointer',
          background: isSelected ? 'var(--bg-hover)' : 'transparent',
          borderRadius: 'var(--radius-sm)',
          color: isSelected ? 'var(--accent)' : 'var(--text)',
        }}
        onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = 'rgba(255,255,255,0.04)' }}
        onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = '' }}
      >
        <span
          onClick={canExpand ? handleToggle : undefined}
          style={{ width: 14, fontSize: 10, color: 'var(--text-dim)', flexShrink: 0, userSelect: 'none',
            cursor: canExpand ? 'pointer' : 'default' }}
        >
          {canExpand ? (isLoading ? '…' : expanded ? '▾' : '▸') : ''}
        </span>
        <span style={{ fontSize: 'var(--font-size-sm)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {label}
        </span>
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
              onSelect={onSelect}
              entityType={entityType}
              mode={mode}
              expandSet={expandSet}
              hideInverse={hideInverse}
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
}

const EMPTY_SET = new Set<string>()

export default function ClassTree({ ontologyId, versionId, selectedIri, onSelect, entityType = 'class', mode = 'asserted', revealIri, hideInverse = false }: Props) {
  const asserted = useClassTreeNodes(mode === 'asserted' ? ontologyId : null, mode === 'asserted' ? versionId : null, null, entityType, hideInverse)
  const inferred = useInferredTreeNodes(mode === 'inferred' ? ontologyId : null, mode === 'inferred' ? versionId : null, null)

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
    <ul ref={containerRef} style={{ listStyle: 'none' }}>
      {roots.map(term => (
        <TreeNode
          key={term.iri}
          ontologyId={ontologyId}
          versionId={versionId}
          term={term}
          depth={0}
          selectedIri={selectedIri}
          onSelect={onSelect}
          entityType={entityType}
          mode={mode}
          expandSet={expandSet}
          hideInverse={hideInverse}
        />
      ))}
    </ul>
  )
}
