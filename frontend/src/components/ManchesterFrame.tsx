import { Link } from 'react-router-dom'
import type { ManchesterFrame as Frame, ManchesterLine, ManchesterToken } from '../lib/api'

interface Props {
  frame: Frame
  /**
   * Ontology shortname used to build entity-page links for IRI tokens that
   * are in_ontology=true. If unset, all tokens render as inert spans (no Link).
   */
  shortname: string | null
}

const COLOR_BY_OP: Record<'added' | 'removed', string> = {
  added:   '#3fb950',
  removed: '#f85149',
}

function markerFor(op: ManchesterLine['op']): string {
  if (op === 'added')   return '+ '
  if (op === 'removed') return '- '
  return '  '
}

function colorFor(op: ManchesterLine['op']): string {
  if (op === 'added' || op === 'removed') return COLOR_BY_OP[op]
  return 'var(--text)'
}

function badgeText(source: ManchesterLine['source']): string | null {
  if (source === 'asserted') return '[asserted]'
  if (source === 'inferred') return '[inferred]'
  return null
}

function entityUrl(shortname: string, iri: string): string {
  return `/ontologies/${shortname}?term=${encodeURIComponent(iri)}`
}

function renderToken(
  tok: ManchesterToken,
  key: number,
  shortname: string | null,
): JSX.Element {
  if (tok.t === 'text') {
    return <span key={key}>{tok.v}</span>
  }
  if (tok.in_ontology && shortname) {
    return (
      <Link
        key={key}
        to={entityUrl(shortname, tok.iri)}
        title={tok.iri}
        style={{ color: 'inherit', textDecoration: 'underline' }}
      >
        {tok.label}
      </Link>
    )
  }
  return (
    <span key={key} title={tok.iri} style={{ cursor: 'help' }}>
      {tok.label}
    </span>
  )
}

export default function ManchesterFrame({ frame, shortname }: Props) {
  return (
    <pre
      style={{
        margin: 0,
        padding: '0.5rem 0.75rem',
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border)',
        borderRadius: 4,
        fontFamily: 'var(--font-mono, ui-monospace, monospace)',
        fontSize: 12,
        lineHeight: 1.45,
        whiteSpace: 'pre',
        overflowX: 'auto',
      }}
    >
      {frame.lines.map((line, i) => {
        const badge = badgeText(line.source)
        return (
          <div key={i} style={{ color: colorFor(line.op) }}>
            {markerFor(line.op)}
            {line.tokens.map((t, j) => renderToken(t, j, shortname))}
            {badge && (
              <span
                style={{
                  marginLeft: 8,
                  fontSize: '0.8em',
                  fontStyle: 'italic',
                  color: 'var(--text-dim)',
                }}
              >
                {badge}
              </span>
            )}
          </div>
        )
      })}
    </pre>
  )
}
