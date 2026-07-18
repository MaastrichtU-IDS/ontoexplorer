import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTerm, useTermExpanded } from '../hooks/useTerm'
import { useOntologyProfile } from '../hooks/useOntologyProfile'
import { useOntologyMeta } from '../hooks/useOntologyMeta'
import { ClassRef, ClassExprNode, InferredExprEntry, PropertyUsage, ClassUsageEntry, SchemaProperty, InheritedSchemaProperty, OntologyProfileData, OntologyMetaProfile, api } from '../lib/api'
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
  lang?: string | null
}

function filterLangLabels(entries: { value: string; lang: string | null }[], lang: string | null) {
  const dedup = (arr: typeof entries) => {
    const seen = new Set<string>()
    return arr.filter(e => { const k = e.value; return seen.has(k) ? false : (seen.add(k), true) })
  }
  if (!lang) return dedup(entries)
  const preferred = entries.filter(e => e.lang === lang)
  if (preferred.length > 0) return dedup(preferred)
  const untagged = entries.filter(e => !e.lang)
  if (untagged.length > 0) return dedup(untagged)
  const english = entries.filter(e => e.lang === 'en')
  if (english.length > 0) return dedup(english)
  return dedup(entries)
}

function LangBadge({ lang }: { lang: string | null | undefined }) {
  if (!lang) return null
  return (
    <span style={{
      fontSize: 9, padding: '1px 5px', borderRadius: 3,
      background: 'var(--bg-secondary)', border: '1px solid var(--border)',
      color: 'var(--text-dim)', fontWeight: 600, letterSpacing: 0.3, flexShrink: 0,
    }}>
      {lang}
    </span>
  )
}

// Standardized label-prefixed paragraph block — used for Definition,
// Elucidation, and similar role-named annotations rendered above the
// generic Annotations table. Renders nothing when values is empty.
function LabeledTextBlock({ label, values, lang, fallback }: {
  label: string
  values: { value: string; lang: string | null }[]
  lang?: string | null
  fallback?: string | null
}) {
  const filtered = filterLangLabels(values, lang ?? null)
  if (filtered.length === 0 && !fallback) return null
  return (
    <div style={{ marginBottom: 14 }}>
      {filtered.length > 0 ? filtered.map((d, i) => (
        <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'flex-start', marginBottom: filtered.length > 1 ? 6 : 0 }}>
          <p style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', lineHeight: 1.6, margin: 0, flex: 1 }}>
            <span style={{ color: 'var(--text-dim)', fontWeight: 600 }}>{label}: </span>
            {d.value}
          </p>
          {filtered.length > 1 && <LangBadge lang={d.lang} />}
        </div>
      )) : (
        <p style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', lineHeight: 1.6, margin: 0 }}>
          <span style={{ color: 'var(--text-dim)', fontWeight: 600 }}>{label}: </span>
          {fallback}
        </p>
      )}
    </div>
  )
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
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <Link
        to={`/ontologies/${slug}/${vid}?term=${encodeURIComponent(c.iri)}`}
        style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none' }}
        onMouseEnter={e => (e.currentTarget.style.textDecoration = 'underline')}
        onMouseLeave={e => (e.currentTarget.style.textDecoration = 'none')}
      >
        {c.label}
      </Link>
      {c.source && <SourceBadge source={c.source} />}
    </span>
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

// MINIMAL rendering for the new Manchester-string justification shape (SP3 Task 4).
// The reasoner-service now renders every justification line as a plain Manchester
// string instead of a structured ClassExprNode axiom, so this just lists the
// strings. Task 6 replaces this with proper Manchester token/IRI-link rendering.
function JustificationDisplay({ justifications }: {
  justifications: string[][]
}) {
  return (
    <div style={{ marginTop: 6, paddingLeft: 10, borderLeft: '2px solid var(--border)' }}>
      {justifications.map((just, i) => (
        <div key={i} style={{ marginBottom: i < justifications.length - 1 ? 8 : 0 }}>
          {justifications.length > 1 && (
            <div style={{ fontSize: 9, color: 'var(--text-dim)', marginBottom: 3, textTransform: 'uppercase', letterSpacing: 0.5 }}>
              Justification {i + 1}
            </div>
          )}
          {just.map((line, j) => (
            <div key={j} style={{ fontSize: 11, lineHeight: 1.7, fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>
              {line}
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
            <JustificationDisplay justifications={data.justifications} />
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

function InferredExprRow({ entry, slug, vid, ontologyId, versionId, termIri }: {
  entry: InferredExprEntry; slug: string; vid: string
  ontologyId: string; versionId: string; termIri: string
}) {
  const [expanded, setExpanded] = useState(false)
  const { data, isLoading, isError } = useQuery({
    queryKey: ['justification', versionId, termIri, entry.from_iri],
    queryFn: () => api.ontologies.justification(ontologyId, versionId, termIri, entry.from_iri),
    enabled: expanded,
    staleTime: 0,
    retry: false,
  })

  // MINIMAL: no longer synthesizes an extra "from_iri disjointWith expr" line
  // (that required structured ClassExprNode axioms; justifications are now
  // plain Manchester strings). Task 6 re-adds this via proper string rendering.
  const displayJusts = data?.justifications

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
            <JustificationDisplay justifications={displayJusts} />
          )}
        </div>
      )}
    </div>
  )
}

function InferredExprList({ entries, slug, vid, ontologyId, versionId, termIri }: {
  entries: InferredExprEntry[]; slug: string; vid: string
  ontologyId: string; versionId: string; termIri: string
}) {
  if (entries.length === 0) return null
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginBottom: 8 }}>
      {entries.map((entry, i) => (
        <InferredExprRow key={i} entry={entry} slug={slug} vid={vid}
          ontologyId={ontologyId} versionId={versionId} termIri={termIri} />
      ))}
    </div>
  )
}

function propLabel(p: SchemaProperty): string {
  return p.prop_label || p.prop_iri.split(/[#/]/).pop() || p.prop_iri
}

function RangeLinks({ ranges, slug, vid }: { ranges: Array<{ iri: string; label: string | null }>; slug: string; vid: string }) {
  if (ranges.length === 0) return <span style={{ color: 'var(--text-dim)' }}>—</span>
  return (
    <span style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 2px' }}>
      {ranges.map((r, i) => (
        <span key={i} style={{ display: 'flex', alignItems: 'center' }}>
          <IriLink iri={r.iri} label={r.label || r.iri.split(/[#/]/).pop() || r.iri} slug={slug} vid={vid} />
          {i < ranges.length - 1 && <span style={{ color: 'var(--text-dim)', marginLeft: 1 }}>,</span>}
        </span>
      ))}
    </span>
  )
}

function DomainPropertiesTable({ props: items, slug, vid }: { props: SchemaProperty[]; slug: string; vid: string }) {
  if (items.length === 0) return null
  // Group by prop_iri, collecting all distinct ranges
  const grouped = new Map<string, { prop: SchemaProperty; ranges: Array<{ iri: string; label: string | null }> }>()
  for (const item of items) {
    if (!grouped.has(item.prop_iri)) {
      grouped.set(item.prop_iri, { prop: item, ranges: [] })
    }
    if (item.range_iri) {
      const g = grouped.get(item.prop_iri)!
      if (!g.ranges.some(r => r.iri === item.range_iri)) {
        g.ranges.push({ iri: item.range_iri, label: item.range_label })
      }
    }
  }
  const rows = Array.from(grouped.values())
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--font-size-sm)' }}>
      <thead>
        <tr style={{ borderBottom: '1px solid var(--border)' }}>
          {['Property', 'Range'].map(h => (
            <th key={h} style={{
              padding: '4px 8px', textAlign: 'left',
              color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', fontWeight: 500,
            }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map(({ prop, ranges }, i) => (
          <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
            <td style={{ padding: '5px 8px', verticalAlign: 'top' }}>
              <IriLink iri={prop.prop_iri} label={propLabel(prop)} slug={slug} vid={vid} />
            </td>
            <td style={{ padding: '5px 8px', verticalAlign: 'top' }}>
              <RangeLinks ranges={ranges} slug={slug} vid={vid} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function InheritedDomainPropertiesTable({ props: items, slug, vid }: { props: InheritedSchemaProperty[]; slug: string; vid: string }) {
  if (items.length === 0) return null
  // Group by (prop_iri, from_iri), collecting all distinct ranges
  const grouped = new Map<string, { prop: InheritedSchemaProperty; ranges: Array<{ iri: string; label: string | null }> }>()
  for (const item of items) {
    const key = `${item.prop_iri}\0${item.from_iri}`
    if (!grouped.has(key)) {
      grouped.set(key, { prop: item, ranges: [] })
    }
    if (item.range_iri) {
      const g = grouped.get(key)!
      if (!g.ranges.some(r => r.iri === item.range_iri)) {
        g.ranges.push({ iri: item.range_iri, label: item.range_label })
      }
    }
  }
  const rows = Array.from(grouped.values())
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--font-size-sm)' }}>
      <thead>
        <tr style={{ borderBottom: '1px solid var(--border)' }}>
          {['Property', 'Range', 'Inherited from'].map(h => (
            <th key={h} style={{
              padding: '4px 8px', textAlign: 'left',
              color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', fontWeight: 500,
            }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map(({ prop, ranges }, i) => (
          <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
            <td style={{ padding: '5px 8px', verticalAlign: 'top' }}>
              <IriLink iri={prop.prop_iri} label={propLabel(prop)} slug={slug} vid={vid} />
            </td>
            <td style={{ padding: '5px 8px', verticalAlign: 'top' }}>
              <RangeLinks ranges={ranges} slug={slug} vid={vid} />
            </td>
            <td style={{ padding: '5px 8px', verticalAlign: 'top' }}>
              <IriLink iri={prop.from_iri} label={prop.from_label || prop.from_iri.split(/[#/]/).pop() || prop.from_iri} slug={slug} vid={vid} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Section({ label, children, headerRight }: {
  label: string
  children: React.ReactNode
  headerRight?: React.ReactNode
}) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 1,
        marginBottom: 6,
      }}>
        <span style={{ flex: 1 }}>{label}</span>
        {headerRight}
      </div>
      {children}
    </div>
  )
}

/**
 * Generic pager around a usage-style table — holds locally appended rows and
 * renders a "Show more" button below the table when more pages are available.
 * Each click hits the paginated /term-usage endpoint for the next slice.
 */
function UsagePager<T>({ initial, initialHasMore, fetchPage, children }: {
  initial: T[]
  initialHasMore: boolean
  fetchPage: (offset: number) => Promise<{ items: T[]; has_more: boolean }>
  children: (rows: T[]) => React.ReactNode
}) {
  const [rows, setRows] = useState<T[]>(initial)
  const [hasMore, setHasMore] = useState(initialHasMore)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function loadMore() {
    setLoading(true)
    setError(null)
    try {
      const page = await fetchPage(rows.length)
      setRows([...rows, ...page.items])
      setHasMore(page.has_more)
    } catch (e) {
      setError((e as Error).message || 'Failed to load more')
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      {children(rows)}
      {hasMore && (
        <div style={{ marginTop: 8, display: 'flex', justifyContent: 'center' }}>
          <button
            type="button"
            onClick={loadMore}
            disabled={loading}
            style={{
              padding: '5px 12px', fontSize: 12,
              background: 'var(--bg-secondary)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
              color: loading ? 'var(--text-dim)' : 'var(--text)',
              cursor: loading ? 'wait' : 'pointer',
            }}
            onMouseEnter={e => { if (!loading) (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)' }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)' }}
          >
            {loading ? 'Loading…' : `Show more (showing ${rows.length})`}
          </button>
        </div>
      )}
      {error && (
        <div style={{ marginTop: 6, fontSize: 11, color: 'var(--error, #e06c75)', textAlign: 'center' }}>
          {error}
        </div>
      )}
    </>
  )
}


function UsageTable({ usage, propIri, propLabel, slug, vid }: {
  usage: PropertyUsage[]; propIri: string; propLabel: string; slug: string; vid: string
}) {
  if (usage.length === 0) return <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>No axioms found</span>

  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--font-size-sm)' }}>
      <thead>
        <tr style={{ borderBottom: '1px solid var(--border)' }}>
          {['Class', 'Axiom', 'Relation', 'Restriction', 'Filler'].map(h => (
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
              <code style={{ color: 'var(--accent-purple)', fontSize: 11 }}>{u.relation ?? 'subClassOf'}</code>
            </td>
            <td style={{ padding: '5px 8px', verticalAlign: 'top' }}>
              <IriLink iri={propIri} label={propLabel} slug={slug} vid={vid} />
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

function ClassUsageTable({ usage, classIri, classLabel, slug, vid }: {
  usage: ClassUsageEntry[]; classIri: string; classLabel: string; slug: string; vid: string
}) {
  if (usage.length === 0) return <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>No axioms found</span>

  return (
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--font-size-sm)' }}>
      <thead>
        <tr style={{ borderBottom: '1px solid var(--border)' }}>
          {['Class', 'Axiom', 'Relation', 'Restriction', 'Filler'].map(h => (
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
              <code style={{ color: 'var(--accent-purple)', fontSize: 11 }}>{u.relation ?? 'subClassOf'}</code>
            </td>
            <td style={{ padding: '5px 8px', verticalAlign: 'top' }}>
              {u.property_iri ? (
                <IriLink iri={u.property_iri} label={u.property_label ?? u.property_iri} slug={slug} vid={vid} />
              ) : (
                <span style={{ color: 'var(--text-dim)' }}>—</span>
              )}
            </td>
            <td style={{ padding: '5px 8px', verticalAlign: 'top' }}>
              {u.restriction ? (
                <code style={{ color: 'var(--accent-blue)', fontSize: 11 }}>{u.restriction}</code>
              ) : (
                <span style={{ color: 'var(--text-dim)' }}>—</span>
              )}
            </td>
            <td style={{ padding: '5px 8px', verticalAlign: 'top' }}>
              <IriLink iri={classIri} label={classLabel} slug={slug} vid={vid} />
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
  'http://purl.obolibrary.org/obo/IAO_0000600',  // elucidation
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

// Class body renders subClassOf / equivalent / disjoint / disjointUnion in
// dedicated sections — skip those in the annotations table.
const CLASS_HANDLED_PREDICATES = new Set([
  ...HANDLED_PREDICATES,
  'http://www.w3.org/2000/01/rdf-schema#subClassOf',
  'http://www.w3.org/2002/07/owl#equivalentClass',
  'http://www.w3.org/2002/07/owl#disjointWith',
  'http://www.w3.org/2002/07/owl#disjointUnionOf',
])

// Property body renders domain / range / inverseOf / subPropertyOf /
// propertyChainAxiom in dedicated sections.
const PROPERTY_HANDLED_PREDICATES = new Set([
  ...HANDLED_PREDICATES,
  'http://www.w3.org/2000/01/rdf-schema#domain',
  'http://www.w3.org/2000/01/rdf-schema#range',
  'http://www.w3.org/2000/01/rdf-schema#subPropertyOf',
  'http://www.w3.org/2002/07/owl#inverseOf',
  'http://www.w3.org/2002/07/owl#propertyChainAxiom',
  'http://www.w3.org/2002/07/owl#equivalentProperty',
])

// Toggle persisted across sessions. Default 'standardized' — same role name
// across ontologies for label/definition/synonym/deprecated/example; the
// long tail keeps the property's own rdfs:label. 'original' shows the
// property's own label for every row (no profile role overlay).
type LabelMode = 'standardized' | 'original'
const LABEL_MODE_KEY = 'term-panel-label-mode'

function useLabelMode(): [LabelMode, (m: LabelMode) => void] {
  const [mode, setMode] = useState<LabelMode>(() => {
    const stored = (typeof localStorage !== 'undefined' && localStorage.getItem(LABEL_MODE_KEY)) || ''
    return stored === 'original' ? 'original' : 'standardized'
  })
  useEffect(() => {
    function onStorage(e: StorageEvent) {
      if (e.key === LABEL_MODE_KEY && e.newValue) {
        setMode(e.newValue === 'original' ? 'original' : 'standardized')
      }
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])
  function update(m: LabelMode) {
    localStorage.setItem(LABEL_MODE_KEY, m)
    setMode(m)
  }
  return [mode, update]
}

// Term-level roles from OntologyProfile (label/definition/synonym/...).
const TERM_ROLE_NAME: Record<keyof Pick<OntologyProfileData,
  'label_props' | 'definition_props' | 'elucidation_props' | 'synonym_props' | 'deprecated_props' | 'example_props'>, string> = {
  label_props:       'Label',
  definition_props:  'Definition',
  elucidation_props: 'Elucidation',
  synonym_props:     'Synonym',
  deprecated_props:  'Deprecated',
  example_props:     'Example',
}

// Ontology-document-level roles from OntologyMetaProfile (title/creator/...).
// These IRIs can also appear on individual classes (e.g. dc:contributor on a
// class), so we resolve them to the same standardized name in either context.
const META_ROLE_NAME: Partial<Record<keyof OntologyMetaProfile, string>> = {
  title_props:                'Title',
  shortname_props:            'Shortname',
  description_props:          'Description',
  creator_props:              'Creator',
  contributor_props:          'Contributor',
  publisher_props:            'Publisher',
  license_props:              'License',
  homepage_props:             'Homepage',
  version_info_props:         'Version Info',
  version_iri_props:          'Version IRI',
  prefix_props:               'Namespace Prefix',
  namespace_uri_props:        'Namespace URI',
  created_props:              'Created',
  modified_props:             'Modified',
  language_props:             'Language',
  citation_props:             'Citation',
  funding_props:              'Funding',
  status_props:               'Status',
  syntax_props:               'Syntax',
  see_also_props:             'See Also',
  is_defined_by_props:        'Defined By',
  competency_question_props:  'Competency Question',
  endorsed_by_props:          'Endorsed By',
  relies_on_props:            'Relies On',
  similar_props:              'Similar',
  generalizes_props:          'Generalizes',
  specializes_props:          'Specializes',
  known_usage_props:          'Known Usage',
  used_in_project_props:      'Used In Project',
}

function buildRoleMap(
  profile: OntologyProfileData | undefined,
  meta: OntologyMetaProfile | undefined,
): Map<string, string> {
  const m = new Map<string, string>()
  // Term-level roles win on collision (more specific to the entity type).
  if (profile) {
    for (const key of Object.keys(TERM_ROLE_NAME) as (keyof typeof TERM_ROLE_NAME)[]) {
      for (const iri of (profile[key] ?? [])) m.set(iri, TERM_ROLE_NAME[key])
    }
  }
  if (meta) {
    for (const key of Object.keys(META_ROLE_NAME) as (keyof typeof META_ROLE_NAME)[]) {
      const iris = (meta[key] as string[] | undefined) ?? []
      const name = META_ROLE_NAME[key]
      if (!name) continue
      for (const iri of iris) if (!m.has(iri)) m.set(iri, name)
    }
  }
  return m
}

function resolvePredLabel(
  pred: string,
  mode: LabelMode,
  propertyLabels: Record<string, string>,
  roleMap: Map<string, string>,
): string {
  if (mode === 'standardized') {
    const role = roleMap.get(pred)
    if (role) return role
  }
  return propertyLabels[pred] || PRED_SHORT[pred] || (() => {
    const frag = pred.replace(/[/#]+$/, '')
    return frag.includes('#') ? frag.split('#').pop()! : frag.split('/').pop()!
  })()
}

function LabelModeToggleLink({ mode, onChange }: { mode: LabelMode; onChange: (m: LabelMode) => void }) {
  const next: LabelMode = mode === 'standardized' ? 'original' : 'standardized'
  const text = next === 'original' ? 'View original annotations' : 'View standardized annotations'
  return (
    <button
      onClick={() => onChange(next)}
      style={{
        background: 'none', border: 'none', cursor: 'pointer',
        color: 'var(--accent)', fontSize: 11, padding: '6px 0 0 0',
      }}
      onMouseEnter={e => (e.currentTarget.style.textDecoration = 'underline')}
      onMouseLeave={e => (e.currentTarget.style.textDecoration = 'none')}
    >
      {text} →
    </button>
  )
}

// Inline truncation for long literal values (typically `Example` paragraphs)
// with a small "more…" / "less" toggle.
function TruncatedLiteral({ value, max = 100 }: { value: string; max?: number }) {
  const [expanded, setExpanded] = useState(false)
  if (value.length <= max) return <span>{value}</span>
  return (
    <span>
      {expanded ? value : value.slice(0, max).trimEnd() + '… '}
      <button
        onClick={() => setExpanded(v => !v)}
        style={{
          background: 'none', border: 'none', cursor: 'pointer',
          color: 'var(--accent)', fontSize: 10, padding: 0, marginLeft: 2,
        }}
      >
        {expanded ? 'less' : 'more…'}
      </button>
    </span>
  )
}

// Display order for standardized roles in the Annotations table. The four
// term-level roles come first (Label/Definition/Synonym/Example — Deprecated
// is rendered as a header chip, not as a row), followed by ontology-document
// roles in declaration order; anything outside this list sorts alphabetically
// at the bottom.
const STANDARDIZED_ORDER: string[] = [
  'Label', 'Definition', 'Elucidation', 'Synonym', 'Example',
  ...Object.values(META_ROLE_NAME).filter((s): s is string => !!s),
]
const STANDARDIZED_RANK = new Map(STANDARDIZED_ORDER.map((name, i) => [name, i]))

function AnnotationsSection({
  properties, propertyLabels, handled, roleMap, slug, versionId, lang,
}: {
  properties: Record<string, { value: string; lang: string | null }[]>
  propertyLabels: Record<string, string>
  handled: Set<string>
  roleMap: Map<string, string>
  slug: string
  versionId: string
  lang?: string | null
}) {
  const [mode, setMode] = useLabelMode()

  // Underlying pool: everything not already in a dedicated section and not
  // deprecated (which becomes a header chip).
  const allCandidates = Object.entries(properties)
    .filter(([pred]) => !handled.has(pred))
    .filter(([pred]) => roleMap.get(pred) !== 'Deprecated')

  if (allCandidates.length === 0) return null

  // STD shows only profile/meta-profile standardized annotations. ORIG reveals
  // every predicate (so the long tail of ontology-supplied annotations is
  // still reachable for users who want the full picture).
  const visible = allCandidates
    .filter(([pred]) => mode === 'original' || roleMap.has(pred))
    .map(([pred, values]) => ({
      pred,
      values,
      displayLabel: resolvePredLabel(pred, mode, propertyLabels, roleMap),
    }))
    .sort((a, b) => {
      const ai = STANDARDIZED_RANK.get(a.displayLabel) ?? -1
      const bi = STANDARDIZED_RANK.get(b.displayLabel) ?? -1
      if (ai !== -1 && bi !== -1) return ai - bi
      if (ai !== -1) return -1
      if (bi !== -1) return 1
      return a.displayLabel.localeCompare(b.displayLabel)
    })

  return (
    <div style={{ marginBottom: 16 }}>
      {visible.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--font-size-sm)' }}>
          <tbody>
            {visible.map(({ pred, values, displayLabel }) => {
              const iris = values.filter(v => v.value.startsWith('http://') || v.value.startsWith('https://'))
              const literals = values.filter(v => !v.value.startsWith('http://') && !v.value.startsWith('https://'))
              const filteredLiterals = filterLangLabels(literals, lang ?? null)
              const displayVals = [...iris, ...filteredLiterals]
              return (
                <tr key={pred} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', verticalAlign: 'top' }}>
                  <td style={{ padding: '4px 10px 4px 0', color: 'var(--text-dim)', whiteSpace: 'nowrap', width: 1, fontSize: 11 }}
                      title={pred}>
                    {displayLabel}
                  </td>
                  <td style={{ padding: '4px 0', color: 'var(--text-muted)', wordBreak: 'break-word' }}>
                    {displayVals.map((entry, i) => {
                      const v = entry.value
                      const isIri = v.startsWith('http://') || v.startsWith('https://')
                      return (
                        <div key={i} style={{ display: 'flex', alignItems: 'baseline', gap: 4, marginBottom: 2 }}>
                          {isIri
                            ? <IriLink iri={v} label={v.split(/[#/]/).pop() ?? v} slug={slug} vid={versionId} />
                            : <TruncatedLiteral value={v} />}
                          <LangBadge lang={entry.lang} />
                        </div>
                      )
                    })}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      <LabelModeToggleLink mode={mode} onChange={setMode} />
    </div>
  )
}

function IndividualBody({ data, slug, roleMap, versionId, lang }: {
  data: ReturnType<typeof useTerm>['data'] & {}
  slug: string
  roleMap: Map<string, string>
  versionId: string
  lang?: string | null
}) {
  return (
    <div style={{ flex: 1, padding: '10px 16px', overflow: 'auto' }}>
      <LabeledTextBlock
        label="Definition"
        values={data.rawDefinitions}
        lang={lang}
        fallback={data.rawDefinitions.length === 0 ? data.definition : null}
      />
      <LabeledTextBlock
        label="Elucidation"
        values={data.rawElucidations}
        lang={lang}
      />

      <AnnotationsSection
        properties={data.rawProperties}
        propertyLabels={data.propertyLabels}
        handled={HANDLED_PREDICATES}
        roleMap={roleMap}
        slug={slug} versionId={versionId} lang={lang}
      />

      {data.typeOf.length > 0 && (
        <Section label="Instance of">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {data.typeOf.map(c => <ClassBubble key={c.iri} c={c} slug={slug} vid={versionId} />)}
          </div>
        </Section>
      )}
    </div>
  )
}

function PropertyBody({ data, slug, ontologyId, roleMap, versionId, lang }: {
  data: ReturnType<typeof useTerm>['data'] & {}
  slug: string
  ontologyId: string
  roleMap: Map<string, string>
  versionId: string
  lang?: string | null
}) {
  const shortLabel = (iri: string) => iri.split(/[#/]/).pop() ?? iri

  return (
    <div style={{ flex: 1, padding: '10px 16px', overflow: 'auto' }}>
      <LabeledTextBlock
        label="Definition"
        values={data.rawDefinitions}
        lang={lang}
        fallback={data.rawDefinitions.length === 0 ? data.definition : null}
      />
      <LabeledTextBlock
        label="Elucidation"
        values={data.rawElucidations}
        lang={lang}
      />

      {(data.rawSynonyms.length > 0 || data.synonyms.exact.length > 0 || data.synonyms.related.length > 0) && (() => {
        const filteredSyns = filterLangLabels(data.rawSynonyms, lang ?? null)
        return (
        <Section label="Synonyms">
          {filteredSyns.length > 0 ? (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {filteredSyns.map((s, i) => (
                <span key={i} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 'var(--font-size-sm)', color: 'var(--text-muted)' }}>
                  {s.value}{filteredSyns.length > 1 && <LangBadge lang={s.lang} />}
                </span>
              ))}
            </div>
          ) : (
            <div style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)' }}>
              {[...data.synonyms.exact, ...data.synonyms.related].join(' · ')}
            </div>
          )}
        </Section>
        )
      })()}

      <AnnotationsSection
        properties={data.rawProperties}
        propertyLabels={data.propertyLabels}
        handled={PROPERTY_HANDLED_PREDICATES}
        roleMap={roleMap}
        slug={slug} versionId={versionId} lang={lang}
      />

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

      <Section label={`Used in axioms${data.usage.length > 0 ? ` (${data.usage.length}${data.usageHasMore ? '+' : ''})` : ''}`}>
        <UsagePager<PropertyUsage>
          initial={data.usage}
          initialHasMore={!!data.usageHasMore}
          fetchPage={async (offset) => {
            const page = await api.ontologies.termUsagePage(ontologyId!, versionId, data.iri, offset)
            return { items: page.items as PropertyUsage[], has_more: page.has_more }
          }}
        >
          {(rows) => (
            <UsageTable
              usage={rows}
              propIri={data.iri}
              propLabel={data.label || data.iri.split(/[#/]/).pop() || data.iri}
              slug={slug}
              vid={versionId}
            />
          )}
        </UsagePager>
      </Section>
    </div>
  )
}

export default function TermPanel({ ontologyId, versionId, termIri, slug, singlePane = false, lang }: Props) {
  const { data: baseData, isLoading, error } = useTerm(ontologyId, versionId, termIri, lang)
  // Lazy fetch of the three expensive sections deferred by the backend. Merged
  // into `data` once it arrives so the rendering below doesn't need to branch.
  const { data: expanded } = useTermExpanded(ontologyId, versionId, termIri, lang)
  // Profile + meta fetched at the panel level so the role map can be shared
  // between the header (deprecation chip) and the Annotations section.
  const { data: profile } = useOntologyProfile(ontologyId ?? undefined, versionId)
  const { data: meta }    = useOntologyMeta(ontologyId ?? undefined, versionId)
  const roleMap = buildRoleMap(profile, meta)

  if (isLoading) return <div style={{ padding: '1rem', color: 'var(--text-dim)' }}>Loading…</div>
  if (error || !baseData) return <div style={{ padding: '1rem', color: 'var(--text-dim)' }}>Term not found</div>

  const data = expanded
    ? {
        ...baseData,
        inferredSuperclassExpressions: expanded.inferredSuperclassExpressions,
        inferredDisjointWith: expanded.inferredDisjointWith,
        inheritedSchemaProperties: expanded.inheritedSchemaProperties,
      }
    : baseData

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

  const isDeprecated = (() => {
    const truthy = (s: string) => /^true$/i.test(s) || s === '1' || /^obsolete$/i.test(s)
    // owl:deprecated true is the canonical signal.
    const owlDep = data.rawProperties['http://www.w3.org/2002/07/owl#deprecated'] ?? []
    if (owlDep.some(v => truthy(v.value))) return true
    // Any predicate the profile assigns to the Deprecated role with a truthy value.
    for (const [pred, values] of Object.entries(data.rawProperties)) {
      if (roleMap.get(pred) === 'Deprecated' && values.some(v => truthy(v.value))) return true
    }
    return false
  })()

  const hasNamedSuperclasses = data.superclasses.asserted.length > 0 || data.superclasses.inferred.length > 0
  const hasSubClassOf = hasNamedSuperclasses
    || (data.superclassExpressions?.length ?? 0) > 0
    || (data.inferredSuperclassExpressions?.length ?? 0) > 0
  const hasEquivalentTo     = data.equivalentTo.length > 0
  const hasDisjointWith     = data.disjointWith.length > 0 || data.inferredDisjointWith.length > 0
  const hasDisjointUnionOf  = data.disjointUnionOf.length > 0
  const hasGCAs             = data.generalClassAxioms.length > 0
  const hasSchemaDomain          = data.schemaProperties.length > 0
  const hasInheritedSchemaDomain = data.inheritedSchemaProperties.length > 0

  const pad = singlePane ? '10px 16px' : '10px 12px'

  let body: React.ReactNode

  const classSynsFiltered = filterLangLabels(data.rawSynonyms, lang ?? null)

  if (isIndividual) {
    body = <IndividualBody data={data} slug={slug} roleMap={roleMap} versionId={versionId} lang={lang} />
  } else if (isProperty) {
    body = <PropertyBody data={data} slug={slug} ontologyId={ontologyId!} roleMap={roleMap} versionId={versionId} lang={lang} />
  } else {
    body = (
      <div style={{ flex: 1, padding: pad, overflow: 'auto' }}>
        <LabeledTextBlock
          label="Definition"
          values={data.rawDefinitions}
          lang={lang}
          fallback={data.rawDefinitions.length === 0 ? data.definition : null}
        />
        <LabeledTextBlock
          label="Elucidation"
          values={data.rawElucidations}
          lang={lang}
        />

        {(classSynsFiltered.length > 0 || data.synonyms.exact.length > 0 || data.synonyms.related.length > 0 ||
          data.synonyms.broad.length > 0 || data.synonyms.narrow.length > 0) && (
          <Section label="Synonyms">
            {classSynsFiltered.length > 0 ? (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {classSynsFiltered.map((s, i) => (
                  <span key={i} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 'var(--font-size-sm)', color: 'var(--text-muted)' }}>
                    {s.value}{classSynsFiltered.length > 1 && <LangBadge lang={s.lang} />}
                  </span>
                ))}
              </div>
            ) : (
              <div style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)' }}>
                {[...data.synonyms.exact, ...data.synonyms.related,
                  ...data.synonyms.broad, ...data.synonyms.narrow].join(' · ')}
              </div>
            )}
          </Section>
        )}

        <AnnotationsSection
          properties={data.rawProperties}
          propertyLabels={data.propertyLabels}
          handled={CLASS_HANDLED_PREDICATES}
          roleMap={roleMap}
          slug={slug} versionId={versionId} lang={lang}
        />

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
              ontologyId={ontologyId} versionId={versionId} termIri={termIri} />
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

        {hasSchemaDomain && (
          <Section label={`Domain of (${data.schemaProperties.length})`}>
            <DomainPropertiesTable props={data.schemaProperties} slug={slug} vid={versionId} />
          </Section>
        )}

        {hasInheritedSchemaDomain && (
          <Section label={`Inherited domain of (${data.inheritedSchemaProperties.length})`}>
            <InheritedDomainPropertiesTable props={data.inheritedSchemaProperties} slug={slug} vid={versionId} />
          </Section>
        )}

        {data.classUsage.length > 0 && (
          <Section label={`Used in axioms (${data.classUsage.length}${data.classUsageHasMore ? '+' : ''})`}>
            <UsagePager<ClassUsageEntry>
              initial={data.classUsage}
              initialHasMore={!!data.classUsageHasMore}
              fetchPage={async (offset) => {
                const page = await api.ontologies.termUsagePage(ontologyId!, versionId, data.iri, offset)
                return { items: page.items as ClassUsageEntry[], has_more: page.has_more }
              }}
            >
              {(rows) => (
                <ClassUsageTable
                  usage={rows}
                  classIri={data.iri}
                  classLabel={data.label || data.iri.split(/[#/]/).pop() || data.iri}
                  slug={slug}
                  vid={versionId}
                />
              )}
            </UsagePager>
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
        {data.rawLabels.length > 1 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, flex: '1 1 100%' }}>
            {data.rawLabels.map((l, i) => (
              <span key={i} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                {l.value} <LangBadge lang={l.lang} />
              </span>
            ))}
          </div>
        )}
        <span style={{
          fontSize: 10, background: 'var(--bg)', color: typeColor,
          borderRadius: 3, padding: '1px 5px', textTransform: 'uppercase', flexShrink: 0,
        }}>{typeLabel}</span>
        {isDeprecated && (
          <span
            title="This term is deprecated"
            style={{
              fontSize: 10,
              background: 'rgba(224,108,117,0.12)',
              border: '1px solid rgba(224,108,117,0.4)',
              color: '#e06c75',
              borderRadius: 3, padding: '1px 5px',
              textTransform: 'uppercase', letterSpacing: 0.5,
              fontWeight: 700, flexShrink: 0,
            }}
          >
            Deprecated
          </span>
        )}
        {data.source && <SourceBadge source={data.source} />}
        <CopyChip text={data.iri.split(/[#/]/).pop() ?? data.iri} title={data.iri} />
        <CopyChip text={window.location.href} label="¶" title="Copy permalink" />
      </div>
      {body}
    </div>
  )
}
