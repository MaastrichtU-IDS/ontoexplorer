import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useClassTreeNodes } from '../hooks/useClassTree'
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
  entityType: 'class' | 'property'
  mode: Mode
  expandSet: Set<string>
}

function TreeNode({ ontologyId, versionId, term, depth, selectedIri, onSelect, entityType, mode, expandSet }: NodeProps) {
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
  entityType?: 'class' | 'property'
  mode?: Mode
  revealIri?: string | null
}

const EMPTY_SET = new Set<string>()

export default function ClassTree({ ontologyId, versionId, selectedIri, onSelect, entityType = 'class', mode = 'asserted', revealIri }: Props) {
  const asserted = useClassTreeNodes(mode === 'asserted' ? ontologyId : null, mode === 'asserted' ? versionId : null, null, entityType)
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
    return <div style={{ padding: '0.5rem 1rem', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
      No {entityType === 'property' ? 'properties' : 'classes'} found
    </div>
  }

  return (
    <ul style={{ listStyle: 'none' }}>
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
        />
      ))}
    </ul>
  )
}
