import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTerm } from '../hooks/useTerm'
import { ClassRef, ClassExprNode, InferredExprEntry, JustificationAxiom, PropertyUsage, ClassUsageEntry, api } from '../lib/api'
import SourceBadge from './SourceBadge'

function CopyChip({ text, label, title }: { text: string; label?: string; title?: string }) {
  const [copied, setCopied] = useState(false)
  function handleCopy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <button
      onClick={handleCopy}
      title={title ?? text}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 4,
        background: 'none', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
        color: copied ? 'var(--accent)' : 'var(--text-dim)',
        fontSize: 11, padding: '2px 7px', cursor: 'pointer',
        transition: 'color 0.15s, border-color 0.15s',
        flexShrink: 0,
      }}
      onMouseEnter={e => { if (!copied) e.currentTarget.style.borderColor = 'var(--text-muted)' }}
      onMouseLeave={e => { if (!copied) e.currentTarget.style.borderColor = 'var(--border)' }}
    >
      {copied ? '✓' : label !== undefined ? label : `⎘ ${text}`}
    </button>
  )
}

interface Props {
  ontologyId: string
  versionId: string
  termIri: string
  slug: string
  singlePane?: boolean
}

function IriLink({ iri, label, slug, vid }: { iri: string; label: string; slug: string; vid: string }) {
  return (
    <Link
      to={`/ontologies/${slug}/${vid}?term=${encodeURIComponent(iri)}`}
      style={{ color: 'var(--accent)', textDecoration: 'none', fontSize: 'var(--font-size-sm)' }}
    >
      {label}
    </Link>
  )
}

function ClassBubble({ c, slug, vid }: { c: ClassRef; slug: string; vid: string }) {
  return (
    <Link
      to={`/ontologies/${slug}/${vid}?term=${encodeURIComponent(c.iri)}`}
      style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}
      onMouseEnter={e => (e.currentTarget.style.textDecoration = 'underline')}
      onMouseLeave={e => (e.currentTarget.style.textDecoration = 'none')}
    >
      {c.label}
    </Link>
  )
}

function HierGroup({ label, items, slug, vid }: {
  label?: string; items: ClassRef[]; slug: string; vid: string
}) {
  if (items.length === 0) return null
  return (
    <div style={{ marginBottom: 8 }}>
      {label && (
        <div style={{ marginBottom: 5 }}>
          <span style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5 }}>{label}</span>
        </div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {items.map(c => <ClassBubble key={c.iri} c={c} slug={slug} vid={vid} />)}
      </div>
    </div>
  )
}

function JustificationDisplay({ justifications, slug, vid }: {
  justifications: JustificationAxiom[][]; slug: string; vid: string
}) {
  const sym = (rel: string) => (
    <span style={{ color: 'var(--text-dim)', margin: '0 4px' }}>
      {rel === 'subClassOf' ? '⊑' : rel === 'disjointWith' ? '⊥' : '≡'}
    </span>
  )
  return (
    <div style={{ marginTop: 6, paddingLeft: 10, borderLeft: '2px solid var(--border)' }}>
      {justifications.map((just, i) => (
        <div key={i} style={{ marginBottom: i < justifications.length - 1 ? 8 : 0 }}>
          {justifications.length > 1 && (
            <div style={{ fontSize: 9, color: 'var(--text-dim)', marginBottom: 3, textTransform: 'uppercase', letterSpacing: 0.5 }}>
              Justification {i + 1}
            </div>
          )}
          {just.map((axiom, j) => (
            <div key={j} style={{ fontSize: 11, lineHeight: 1.7 }}>
              <ExprNode node={axiom.sub} slug={slug} vid={vid} />
              {sym(axiom.rel)}
              <ExprNode node={axiom.sup} slug={slug} vid={vid} parens />
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

function InferredClassRow({ c, slug, vid, ontologyId, versionId, termIri }: {
  c: ClassRef; slug: string; vid: string; ontologyId: string; versionId: string; termIri: string
}) {
  const [expanded, setExpanded] = useState(false)
  const { data, isLoading, isError } = useQuery({
    queryKey: ['justification', versionId, termIri, c.iri],
    queryFn: () => api.ontologies.justification(ontologyId, versionId, termIri, c.iri),
    enabled: expanded,
    staleTime: 0,
    retry: false,
  })

  return (
    <div style={{ marginBottom: 4 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <ClassBubble c={c} slug={slug} vid={vid} />
        <button
          onClick={() => setExpanded(e => !e)}
          title="Show justification"
          style={{
            fontSize: 9, padding: '1px 4px', borderRadius: 2, cursor: 'pointer',
            background: 'none', flexShrink: 0,
            color: expanded ? 'var(--accent)' : 'var(--text-dim)',
            border: `1px solid ${expanded ? 'var(--accent)' : 'var(--border)'}`,
          }}
        >
          inference
        </button>
      </div>
      {expanded && (
        <div style={{ marginLeft: 4 }}>
          {isLoading && <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>Computing…</span>}
          {isError && <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>Unavailable</span>}
          {data?.justifications.length === 0 && (
            <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
              {data.timed_out ? 'Still computing — try again' : 'No justification available'}
            </span>
          )}
          {data?.justifications && data.justifications.length > 0 && (
            <JustificationDisplay justifications={data.justifications} slug={slug} vid={vid} />
          )}
        </div>
      )}
    </div>
  )
}

function InferredSuperclasses({ items, slug, vid, ontologyId, versionId, termIri }: {
  items: ClassRef[]; slug: string; vid: string; ontologyId: string; versionId: string; termIri: string
}) {
  if (items.length === 0) return null
  const sorted = [...items].sort((a, b) =>
    (a.label || a.iri).localeCompare(b.label || b.iri, undefined, { sensitivity: 'base' })
  )
  return (
    <div style={{ marginBottom: 8 }}>
      {sorted.map(c => (
        <InferredClassRow key={c.iri} c={c} slug={slug} vid={vid}
          ontologyId={ontologyId} versionId={versionId} termIri={termIri} />
      ))}
    </div>
  )
}

function ExprNode({ node, slug, vid, parens = false }: {
  node: ClassExprNode; slug: string; vid: string; parens?: boolean
}): React.ReactElement {
  const kw = (s: string) => (
    <span style={{ color: 'var(--accent-blue)', fontStyle: 'italic' }}>{s}</span>
  )
  const needsParens = parens
    && node.type !== 'named' && node.type !== 'literal' && node.type !== 'unknown'

  let content: React.ReactNode
  switch (node.type) {
    case 'named':
      content = (
        <Link
          to={`/ontologies/${slug}/${vid}?term=${encodeURIComponent(node.iri)}`}
          style={{ color: 'var(--accent)', textDecoration: 'none' }}
          onMouseEnter={e => (e.currentTarget.style.textDecoration = 'underline')}
          onMouseLeave={e => (e.currentTarget.style.textDecoration = 'none')}
        >
          {node.label.includes(' ') ? `'${node.label}'` : node.label}
        </Link>
      )
      break
    case 'literal':
      content = <span style={{ color: 'var(--text-muted)' }}>{node.value}</span>
      break
    case 'some':
    case 'only':
    case 'value':
      content = (
        <span>
          <ExprNode node={node.property} slug={slug} vid={vid} parens />
          {' '}{kw(node.type)}{' '}
          <ExprNode node={node.filler} slug={slug} vid={vid} parens />
        </span>
      )
      break
    case 'not':
      content = (
        <span>
          {kw('not')}{' '}
          <ExprNode node={node.operand} slug={slug} vid={vid} parens />
        </span>
      )
      break
    case 'and':
    case 'or': {
      const op = node.type
      content = (
        <span>
          {node.operands.map((operand, i) => (
            <React.Fragment key={i}>
              {i > 0 && <> {kw(op)} </>}
              <ExprNode node={operand} slug={slug} vid={vid} parens />
            </React.Fragment>
          ))}
        </span>
      )
      break
    }
    case 'min':
    case 'max':
    case 'exactly':
      content = (
        <span>
          <ExprNode node={node.property} slug={slug} vid={vid} parens />
          {' '}{kw(node.type)}{' '}
          <span style={{ color: 'var(--text-muted)' }}>{node.n}</span>
          {node.filler && <> <ExprNode node={node.filler} slug={slug} vid={vid} parens /></>}
        </span>
      )
      break
    case 'one_of':
      content = (
        <span>
          {'{'}{node.individuals.map((ind, i) => (
            <React.Fragment key={i}>
              {i > 0 && ', '}
              <ExprNode node={ind} slug={slug} vid={vid} />
            </React.Fragment>
          ))}{'}'}
        </span>
      )
      break
    default:
      content = <span style={{ color: 'var(--text-dim)' }}>?</span>
  }

  if (needsParens) {
    return <span><span style={{ color: 'var(--text-dim)' }}>(</span>{content}<span style={{ color: 'var(--text-dim)' }}>)</span></span>
  }
  return <span>{content}</span>
}

function DisjointUnionList({ axioms, slug, vid }: {
  axioms: ClassExprNode[][]; slug: string; vid: string
}) {
  if (axioms.length === 0) return null
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {axioms.map((members, i) => (
        <div key={i} style={{ fontSize: 11, lineHeight: 1.6 }}>
          {members.map((m, j) => (
            <React.Fragment key={j}>
              {j > 0 && <span style={{ color: 'var(--text-dim)' }}>, </span>}
              <ExprNode node={m} slug={slug} vid={vid} />
            </React.Fragment>
          ))}
        </div>
      ))}
    </div>
  )
}

function ClassExprList({ exprs, label, slug, vid }: {
  exprs: ClassExprNode[]; label?: string; slug: string; vid: string
}) {
  if (exprs.length === 0) return null
  return (
    <div style={{ marginBottom: 8 }}>
      {label && (
        <div style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 5 }}>
          {label}
        </div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {exprs.map((expr, i) => (
          <div key={i} style={{
            fontSize: 11, lineHeight: 1.6, wordBreak: 'break-word',
          }}>
            <ExprNode node={expr} slug={slug} vid={vid} />
          </div>
        ))}
      </div>
    </div>
  )
}

function InferredExprRow({ entry, slug, vid, ontologyId, versionId, termIri, appendAxiom }: {
  entry: InferredExprEntry; slug: string; vid: string
  ontologyId: string; versionId: string; termIri: string
  appendAxiom?: JustificationAxiom
}) {
  const [expanded, setExpanded] = useState(false)
  const { data, isLoading, isError } = useQuery({
    queryKey: ['justification', versionId, termIri, entry.from_iri],
    queryFn: () => api.ontologies.justification(ontologyId, versionId, termIri, entry.from_iri),
    enabled: expanded,
    staleTime: 0,
    retry: false,
  })

  const displayJusts = appendAxiom && data?.justifications
    ? data.justifications.map(just => [...just, appendAxiom])
    : data?.justifications

  return (
    <div style={{ marginBottom: 4 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap', fontSize: 11, lineHeight: 1.6 }}>
        <ExprNode node={entry.expr} slug={slug} vid={vid} />
        <span style={{ color: 'var(--text-dim)', fontSize: 10, flexShrink: 0 }}>
          ← <Link
            to={`/ontologies/${slug}/${vid}?term=${encodeURIComponent(entry.from_iri)}`}
            style={{ color: 'var(--text-dim)', textDecoration: 'none' }}
            onMouseEnter={e => (e.currentTarget.style.textDecoration = 'underline')}
            onMouseLeave={e => (e.currentTarget.style.textDecoration = 'none')}
          >
            {entry.from_label}
          </Link>
        </span>
        <button
          onClick={() => setExpanded(e => !e)}
          title="Show justification"
          style={{
            fontSize: 9, padding: '1px 4px', borderRadius: 2, cursor: 'pointer',
            background: 'none', flexShrink: 0,
            color: expanded ? 'var(--accent)' : 'var(--text-dim)',
            border: `1px solid ${expanded ? 'var(--accent)' : 'var(--border)'}`,
          }}
        >
          inference
        </button>
      </div>
      {expanded && (
        <div style={{ marginLeft: 4 }}>
          {isLoading && <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>Computing…</span>}
          {isError && <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>Unavailable</span>}
          {displayJusts?.length === 0 && (
            <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
              {data?.timed_out ? 'Still computing — try again' : 'No justification available'}
            </span>
          )}
          {displayJusts && displayJusts.length > 0 && (
            <JustificationDisplay justifications={displayJusts} slug={slug} vid={vid} />
          )}
        </div>
      )}
    </div>
  )
}

function InferredExprList({ entries, slug, vid, ontologyId, versionId, termIri, makeAppendAxiom }: {
  entries: InferredExprEntry[]; slug: string; vid: string
  ontologyId: string; versionId: string; termIri: string
  makeAppendAxiom?: (entry: InferredExprEntry) => JustificationAxiom
}) {
  if (entries.length === 0) return null
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginBottom: 8 }}>
      {entries.map((entry, i) => (
        <InferredExprRow key={i} entry={entry} slug={slug} vid={vid}
          ontologyId={ontologyId} versionId={versionId} termIri={termIri}
          appendAxiom={makeAppendAxiom?.(entry)} />
      ))}
    </div>
  )
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>
        {label}
      </div>
      {children}
    </div>
  )
}

function UsageTable({ usage, slug, vid }: { usage: PropertyUsage[]; slug: string; vid: string }) {
  if (usage.length === 0) return <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>No axioms found</span>

  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--font-size-sm)' }}>
      <thead>
        <tr style={{ borderBottom: '1px solid var(--border)' }}>
          {['Class', 'Restriction', 'Filler'].map(h => (
            <th key={h} style={{
              padding: '4px 8px', textAlign: 'left',
              color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', fontWeight: 500,
            }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {usage.map((u, i) => (
          <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
            <td style={{ padding: '5px 8px', verticalAlign: 'top' }}>
              <IriLink iri={u.class_iri} label={u.class_label} slug={slug} vid={vid} />
            </td>
            <td style={{ padding: '5px 8px', verticalAlign: 'top' }}>
              <code style={{ color: 'var(--accent-blue)', fontSize: 11 }}>{u.restriction}</code>
            </td>
            <td style={{ padding: '5px 8px', verticalAlign: 'top' }}>
              {u.filler_iri ? (
                <IriLink iri={u.filler_iri} label={u.filler_label ?? u.filler_iri} slug={slug} vid={vid} />
              ) : (
                <span style={{ color: 'var(--text-muted)' }}>{u.filler_label ?? '—'}</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function ClassUsageTable({ usage, slug, vid }: { usage: ClassUsageEntry[]; slug: string; vid: string }) {
  if (usage.length === 0) return <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>No axioms found</span>

  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--font-size-sm)' }}>
      <thead>
        <tr style={{ borderBottom: '1px solid var(--border)' }}>
          {['Class', 'Property', 'Restriction'].map(h => (
            <th key={h} style={{
              padding: '4px 8px', textAlign: 'left',
              color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', fontWeight: 500,
            }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {usage.map((u, i) => (
          <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
            <td style={{ padding: '5px 8px', verticalAlign: 'top' }}>
              <IriLink iri={u.class_iri} label={u.class_label} slug={slug} vid={vid} />
            </td>
            <td style={{ padding: '5px 8px', verticalAlign: 'top' }}>
              {u.property_iri ? (
                <IriLink iri={u.property_iri} label={u.property_label ?? u.property_iri} slug={slug} vid={vid} />
              ) : (
                <span style={{ color: 'var(--text-dim)' }}>—</span>
              )}
            </td>
            <td style={{ padding: '5px 8px', verticalAlign: 'top' }}>
              <code style={{ color: 'var(--accent-blue)', fontSize: 11 }}>{u.restriction}</code>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// Predicates shown in dedicated sections — skip them in the generic annotations table
const HANDLED_PREDICATES = new Set([
  'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
  'http://www.w3.org/2000/01/rdf-schema#label',
  'http://www.w3.org/2000/01/rdf-schema#comment',
  'http://www.w3.org/2002/07/owl#deprecated',
  'http://purl.obolibrary.org/obo/IAO_0000115',  // definition
  'http://purl.obolibrary.org/obo/IAO_0000111',  // preferred label
])

const PRED_SHORT: Record<string, string> = {
  'http://www.w3.org/2000/01/rdf-schema#subClassOf':           'subClassOf',
  'http://www.w3.org/2002/07/owl#sameAs':                      'sameAs',
  'http://www.w3.org/2002/07/owl#differentFrom':               'differentFrom',
  'http://www.w3.org/2004/02/skos/core#exactMatch':            'skos:exactMatch',
  'http://www.w3.org/2004/02/skos/core#closeMatch':            'skos:closeMatch',
  'http://www.w3.org/2004/02/skos/core#broadMatch':            'skos:broadMatch',
  'http://www.w3.org/2004/02/skos/core#narrowMatch':           'skos:narrowMatch',
  'http://www.w3.org/2004/02/skos/core#relatedMatch':          'skos:relatedMatch',
  'http://purl.obolibrary.org/obo/IAO_0000234':                'curator note',
  'http://purl.obolibrary.org/obo/IAO_0000114':                'has curation status',
  'http://purl.obolibrary.org/obo/IAO_0000117':                'term editor',
  'http://purl.obolibrary.org/obo/IAO_0000119':                'definition source',
}

function predShort(iri: string): string {
  if (PRED_SHORT[iri]) return PRED_SHORT[iri]
  const frag = iri.replace(/[/#]+$/, '')
  return frag.includes('#') ? frag.split('#').pop()! : frag.split('/').pop()!
}

function IndividualBody({ data, slug, versionId }: {
  data: ReturnType<typeof useTerm>['data'] & {}
  slug: string
  versionId: string
}) {
  const annotations = Object.entries(data.rawProperties)
    .filter(([pred]) => !HANDLED_PREDICATES.has(pred))
    .sort(([a], [b]) => predShort(a).localeCompare(predShort(b)))

  return (
    <div style={{ flex: 1, padding: '10px 16px', overflow: 'auto' }}>
      {data.definition && (
        <p style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', marginBottom: 14, lineHeight: 1.6 }}>
          {data.definition}
        </p>
      )}

      {data.typeOf.length > 0 && (
        <Section label="Instance of">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {data.typeOf.map(c => <ClassBubble key={c.iri} c={c} slug={slug} vid={versionId} />)}
          </div>
        </Section>
      )}

      {annotations.length > 0 && (
        <Section label="Annotations">
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--font-size-sm)' }}>
            <tbody>
              {annotations.map(([pred, values]) => (
                <tr key={pred} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', verticalAlign: 'top' }}>
                  <td style={{ padding: '4px 10px 4px 0', color: 'var(--text-dim)', whiteSpace: 'nowrap', width: 1, fontSize: 11 }}>
                    {predShort(pred)}
                  </td>
                  <td style={{ padding: '4px 0', color: 'var(--text-muted)', wordBreak: 'break-word' }}>
                    {values.map((entry, i) => {
                      const v = entry.value
                      return (
                        <div key={i}>
                          {v.startsWith('http://') || v.startsWith('https://') ? (
                            <IriLink iri={v} label={v.split(/[#/]/).pop() ?? v} slug={slug} vid={versionId} />
                          ) : v}
                        </div>
                      )
                    })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}
    </div>
  )
}

function PropertyBody({ data, slug, versionId }: {
  data: ReturnType<typeof useTerm>['data'] & {}
  slug: string
  versionId: string
}) {
  const shortLabel = (iri: string) => iri.split(/[#/]/).pop() ?? iri

  return (
    <div style={{ flex: 1, padding: '10px 16px', overflow: 'auto' }}>
      {data.definition && (
        <p style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', marginBottom: 14, lineHeight: 1.6 }}>
          {data.definition}
        </p>
      )}

      {data.characteristics.length > 0 && (
        <Section label="Characteristics">
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {data.characteristics.map(c => (
              <span key={c} style={{
                fontSize: 11, borderRadius: 3, padding: '2px 7px',
                background: 'rgba(80,160,255,0.12)', color: 'var(--accent-blue)',
              }}>{c}</span>
            ))}
          </div>
        </Section>
      )}

      {data.domain.length > 0 && (
        <Section label="Domain">
          {data.domain.map(iri => (
            <div key={iri} style={{ paddingLeft: 8, marginBottom: 2 }}>
              <IriLink iri={iri} label={shortLabel(iri)} slug={slug} vid={versionId} />
            </div>
          ))}
        </Section>
      )}

      {data.range.length > 0 && (
        <Section label="Range">
          {data.range.map(iri => (
            <div key={iri} style={{ paddingLeft: 8, marginBottom: 2 }}>
              {iri.startsWith('http') ? (
                <IriLink iri={iri} label={shortLabel(iri)} slug={slug} vid={versionId} />
              ) : (
                <span style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)' }}>{iri}</span>
              )}
            </div>
          ))}
        </Section>
      )}

      {data.inverseOf.length > 0 && (
        <Section label="Inverse of">
          {data.inverseOf.map(iri => (
            <div key={iri} style={{ paddingLeft: 8, marginBottom: 2 }}>
              <IriLink iri={iri} label={shortLabel(iri)} slug={slug} vid={versionId} />
            </div>
          ))}
        </Section>
      )}

      {(data.synonyms.exact.length > 0 || data.synonyms.related.length > 0) && (
        <Section label="Synonyms">
          <div style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)' }}>
            {[...data.synonyms.exact, ...data.synonyms.related].join(' · ')}
          </div>
        </Section>
      )}

      <Section label={`Used in axioms${data.usage.length > 0 ? ` (${data.usage.length})` : ''}`}>
        <UsageTable usage={data.usage} slug={slug} vid={versionId} />
      </Section>
    </div>
  )
}

export default function TermPanel({ ontologyId, versionId, termIri, slug, singlePane = false }: Props) {
  const { data, isLoading, error } = useTerm(ontologyId, versionId, termIri)

  if (isLoading) return <div style={{ padding: '1rem', color: 'var(--text-dim)' }}>Loading…</div>
  if (error || !data) return <div style={{ padding: '1rem', color: 'var(--text-dim)' }}>Term not found</div>

  const isProperty = data.entityType === 'object_property' || data.entityType === 'data_property'
    || data.entityType === 'annotation_property' || data.entityType === 'property'
  const isIndividual = data.entityType === 'individual'

  const typeColor = data.entityType === 'class' ? 'var(--accent-purple)'
    : isProperty ? 'var(--accent-blue)'
    : isIndividual ? 'var(--accent)' : 'var(--text-muted)'

  const typeLabel = data.entityType === 'class' ? 'class'
    : data.entityType === 'object_property' ? 'object property'
    : data.entityType === 'data_property' ? 'data property'
    : data.entityType === 'annotation_property' ? 'annotation property'
    : data.entityType === 'property' ? 'property'
    : isIndividual ? 'individual'
    : data.entityType

  const hasNamedSuperclasses = data.superclasses.asserted.length > 0 || data.superclasses.inferred.length > 0
  const hasSubClassOf = hasNamedSuperclasses
    || (data.superclassExpressions?.length ?? 0) > 0
    || (data.inferredSuperclassExpressions?.length ?? 0) > 0
  const hasEquivalentTo     = data.equivalentTo.length > 0
  const hasDisjointWith     = data.disjointWith.length > 0 || data.inferredDisjointWith.length > 0
  const hasDisjointUnionOf  = data.disjointUnionOf.length > 0
  const hasGCAs             = data.generalClassAxioms.length > 0

  const pad = singlePane ? '10px 16px' : '10px 12px'

  let body: React.ReactNode

  if (isIndividual) {
    body = <IndividualBody data={data} slug={slug} versionId={versionId} />
  } else if (isProperty) {
    body = <PropertyBody data={data} slug={slug} versionId={versionId} />
  } else {
    body = (
      <div style={{ flex: 1, padding: pad, overflow: 'auto' }}>
        {data.definition && (
          <p style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', marginBottom: 14, lineHeight: 1.6 }}>
            {data.definition}
          </p>
        )}

        {(data.synonyms.exact.length > 0 || data.synonyms.related.length > 0 ||
          data.synonyms.broad.length > 0 || data.synonyms.narrow.length > 0) && (
          <Section label="Synonyms">
            <div style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)' }}>
              {[...data.synonyms.exact, ...data.synonyms.related,
                ...data.synonyms.broad, ...data.synonyms.narrow].join(' · ')}
            </div>
          </Section>
        )}

        {hasSubClassOf && (
          <Section label="Superclass">
            <HierGroup items={data.superclasses.asserted} slug={slug} vid={versionId} />
            <InferredSuperclasses items={data.superclasses.inferred} slug={slug} vid={versionId}
              ontologyId={ontologyId} versionId={versionId} termIri={termIri} />
            <ClassExprList
              exprs={data.superclassExpressions ?? []}
              slug={slug} vid={versionId}
            />
            <InferredExprList
              entries={data.inferredSuperclassExpressions ?? []}
              slug={slug} vid={versionId}
              ontologyId={ontologyId} versionId={versionId} termIri={termIri}
            />
          </Section>
        )}

        {hasEquivalentTo && (
          <Section label="EquivalentTo">
            <ClassExprList exprs={data.equivalentTo} slug={slug} vid={versionId} />
          </Section>
        )}

        {hasDisjointWith && (
          <Section label="DisjointWith">
            <ClassExprList exprs={data.disjointWith} slug={slug} vid={versionId} />
            <InferredExprList entries={data.inferredDisjointWith} slug={slug} vid={versionId}
              ontologyId={ontologyId} versionId={versionId} termIri={termIri}
              makeAppendAxiom={entry => ({
                sub: { type: 'named', iri: entry.from_iri, label: entry.from_label },
                rel: 'disjointWith',
                sup: entry.expr,
              })} />
          </Section>
        )}

        {hasDisjointUnionOf && (
          <Section label="DisjointUnionOf">
            <DisjointUnionList axioms={data.disjointUnionOf} slug={slug} vid={versionId} />
          </Section>
        )}

        {hasGCAs && (
          <Section label="General Class Axioms">
            <ClassExprList exprs={data.generalClassAxioms} slug={slug} vid={versionId} />
          </Section>
        )}

        {data.classUsage.length > 0 && (
          <Section label={`Used in axioms (${data.classUsage.length})`}>
            <ClassUsageTable usage={data.classUsage} slug={slug} vid={versionId} />
          </Section>
        )}
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      <div style={{
        padding: '10px 12px', borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
      }}>
        <span style={{ fontWeight: 600, color: 'var(--accent)', flex: 1 }}>{data.label}</span>
        <span style={{
          fontSize: 10, background: 'var(--bg)', color: typeColor,
          borderRadius: 3, padding: '1px 5px', textTransform: 'uppercase', flexShrink: 0,
        }}>{typeLabel}</span>
        {data.source && <SourceBadge source={data.source} />}
        <CopyChip text={data.iri.split(/[#/]/).pop() ?? data.iri} title={data.iri} />
        <CopyChip text={window.location.href} label="¶" title="Copy permalink" />
        <Link
          to={`/ontologies/${slug}/${versionId}?term=${encodeURIComponent(data.iri)}`}
          style={{ color: 'var(--text-dim)', fontSize: 11, flexShrink: 0 }}
        >
          Open full page ↗
        </Link>
      </div>
      {body}
    </div>
  )
}
