import { useState } from 'react'
import { useClassTreeNodes } from '../hooks/useClassTree'
import { Term } from '../lib/api'

interface NodeProps {
  ontologyId: string
  versionId: string
  term: Term
  depth: number
  selectedIri: string | null
  onSelect: (iri: string) => void
}

function TreeNode({ ontologyId, versionId, term, depth, selectedIri, onSelect }: NodeProps) {
  const [expanded, setExpanded] = useState(false)

  const { data: childData, isLoading } = useClassTreeNodes(
    expanded ? ontologyId : null,
    expanded ? versionId : null,
    expanded ? term.iri : null,
  )

  const children = childData?.terms ?? []
  const isSelected = selectedIri === term.iri
  const label = term.label ?? term.iri.split(/[#/]/).pop() ?? term.iri

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
          onClick={handleToggle}
          style={{ width: 14, fontSize: 10, color: 'var(--text-dim)', flexShrink: 0, userSelect: 'none' }}
        >
          {isLoading ? '…' : expanded ? '▾' : '▸'}
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
}

export default function ClassTree({ ontologyId, versionId, selectedIri, onSelect }: Props) {
  const { data, isLoading } = useClassTreeNodes(ontologyId, versionId, null)
  const roots = data?.terms ?? []

  if (isLoading) {
    return <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>Loading…</div>
  }

  if (roots.length === 0) {
    return <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>No classes found</div>
  }

  return (
    <ul style={{ listStyle: 'none', overflow: 'auto', flex: 1 }}>
      {roots.map(term => (
        <TreeNode
          key={term.iri}
          ontologyId={ontologyId}
          versionId={versionId}
          term={term}
          depth={0}
          selectedIri={selectedIri}
          onSelect={onSelect}
        />
      ))}
    </ul>
  )
}
