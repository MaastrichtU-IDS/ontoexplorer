import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTerm, useTermExpanded } from '../hooks/useTerm'
import { useOntologyProfile } from '../hooks/useOntologyProfile'
import { useOntologyMeta } from '../hooks/useOntologyMeta'
import { ClassRef, ClassExprNode, InferredExprEntry, PropertyUsage, ClassUsageEntry, SchemaProperty, InheritedSchemaProperty, OntologyProfileData, OntologyMetaProfile, Term, ManchesterToken, api } from '../lib/api'
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
  /** The version's reasoner (e.g. "whelk", "rustdl", "konclude"), used to
   *  decide whether the "inference" explain buttons can be enabled — looked
   *  up against `api.reasoners.list()` capabilities. Undefined means unknown
   *  (defaults to enabled rather than wrongly disabling). */
  versionReasoner?: string | null
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

// Recursively collects `{iri: label}` pairs from a ClassExprNode's named
// sub-terms. Used to build a cheap (already-in-memory, no extra fetch)
// IRI→label map for shortening the reasoner's Manchester justification
// strings — see `buildJustificationLabelMap` below.
function collectExprLabels(node: ClassExprNode | undefined, map: Map<string, string>): void {
  if (!node) return
  switch (node.type) {
    case 'named':
      if (!map.has(node.iri)) map.set(node.iri, node.label)
      break
    case 'some':
    case 'only':
    case 'value':
      collectExprLabels(node.property, map)
      collectExprLabels(node.filler, map)
      break
    case 'not':
      collectExprLabels(node.operand, map)
      break
    case 'and':
    case 'or':
      node.operands.forEach(o => collectExprLabels(o, map))
      break
    case 'min':
    case 'max':
    case 'exactly':
      collectExprLabels(node.property, map)
      if (node.filler) collectExprLabels(node.filler, map)
      break
    case 'one_of':
      node.individuals.forEach(ind => collectExprLabels(ind, map))
      break
    default:
      break
  }
}

// Builds an IRI→label map from term data already loaded for the panel (named
// superclasses, equivalent/disjoint/GCA expressions, inferred entries, and
// property labels). This is "cheap" — no extra network round trip — so
// JustificationDisplay uses it to shorten any full IRIs the reasoner's
// Manchester strings mention down to their known label; anything not in the
// map is left as-is (the reasoner-service already renders labels for most
// terms itself, so this only fills gaps).
function buildJustificationLabelMap(data: {
  iri: string
  label: string
  superclasses: { asserted: ClassRef[]; inferred: ClassRef[] }
  equivalentTo: ClassExprNode[]
  disjointWith: ClassExprNode[]
  disjointUnionOf: ClassExprNode[][]
  generalClassAxioms: ClassExprNode[]
  superclassExpressions?: ClassExprNode[]
  inferredSuperclassExpressions?: InferredExprEntry[]
  inferredDisjointWith: InferredExprEntry[]
  propertyLabels: Record<string, string>
}): Map<string, string> {
  const map = new Map<string, string>()
  map.set(data.iri, data.label)
  for (const c of [...data.superclasses.asserted, ...data.superclasses.inferred]) map.set(c.iri, c.label)
  for (const expr of [
    ...data.equivalentTo, ...data.disjointWith, ...data.generalClassAxioms,
    ...(data.superclassExpressions ?? []),
  ]) collectExprLabels(expr, map)
  for (const group of data.disjointUnionOf) for (const expr of group) collectExprLabels(expr, map)
  for (const entry of [...(data.inferredSuperclassExpressions ?? []), ...data.inferredDisjointWith]) {
    if (!map.has(entry.from_iri)) map.set(entry.from_iri, entry.from_label)
    collectExprLabels(entry.expr, map)
  }
  for (const [iri, label] of Object.entries(data.propertyLabels)) if (!map.has(iri)) map.set(iri, label)
  return map
}

// Manchester-syntax keywords, highlighted distinctly from entity names.
const MANCHESTER_KEYWORDS = new Set([
  'SubClassOf', 'EquivalentTo', 'EquivalentClasses', 'DisjointWith', 'DisjointClasses',
  'DisjointUnionOf', 'Type', 'Types', 'SameAs', 'DifferentFrom',
  'SubPropertyOf', 'SubPropertyChain', 'InverseOf', 'Domain', 'Range', 'Characteristics',
  'Functional', 'InverseFunctional', 'Transitive', 'Symmetric', 'Asymmetric',
  'Reflexive', 'Irreflexive',
  'and', 'or', 'not', 'some', 'only', 'value', 'min', 'max', 'exactly', 'that',
  'Self', 'inverse', 'o',
])

// One tokenizer pass over a Manchester line. The reasoner renders entity IRIs
// wrapped in angle brackets (`<http://…>`), so match those first (capturing the
// inner IRI), then bare IRIs, quoted labels, identifiers, whitespace, and any
// single remaining char (punctuation / stray brackets).
const JUST_TOKEN_RE = /<(https?:\/\/[^>\s]+)>|(https?:\/\/[^\s()<>"']+)|('[^']*')|([A-Za-z_][\w-]*)|(\s+)|(.)/g

function iriFragment(iri: string): string {
  const stripped = iri.replace(/[#/]+$/, '')
  return stripped.includes('#') ? stripped.split('#').pop()! : stripped.split('/').pop()! || iri
}

// Renders one Manchester axiom line as coloured, partly-clickable tokens,
// matching the axioms-description styling: entity IRIs become green links to
// their term page (labels resolved via the server `labels` map, IRI on hover),
// Manchester keywords are blue italic, punctuation dimmed.
function ManchesterLine({ line, labels, slug, vid }: {
  line: string; labels: Map<string, string>; slug?: string; vid?: string
}) {
  const parts: JSX.Element[] = []
  let m: RegExpExecArray | null
  JUST_TOKEN_RE.lastIndex = 0
  let k = 0
  const entity = (iri: string) => {
    const raw = labels.get(iri) ?? iriFragment(iri)
    const label = raw.includes(' ') ? `'${raw}'` : raw   // quote multi-word labels, like ExprNode
    if (slug && vid) {
      return (
        <Link
          key={k++}
          to={`/ontologies/${slug}/${vid}?term=${encodeURIComponent(iri)}`}
          title={iri}
          style={{ color: 'var(--accent)', textDecoration: 'none' }}
          onMouseEnter={e => (e.currentTarget.style.textDecoration = 'underline')}
          onMouseLeave={e => (e.currentTarget.style.textDecoration = 'none')}
        >{label}</Link>
      )
    }
    return <span key={k++} title={iri} style={{ color: 'var(--accent)' }}>{label}</span>
  }
  while ((m = JUST_TOKEN_RE.exec(line)) !== null) {
    const [, bracketedIri, bareIri, quoted, ident, ws, ch] = m
    const iri = bracketedIri || bareIri
    if (iri) {
      parts.push(entity(iri))
    } else if (quoted) {
      parts.push(<span key={k++} style={{ color: 'var(--accent)' }}>{quoted.slice(1, -1)}</span>)
    } else if (ident) {
      parts.push(
        MANCHESTER_KEYWORDS.has(ident)
          ? <span key={k++} style={{ color: 'var(--accent-blue)', fontStyle: 'italic' }}>{ident}</span>
          : <span key={k++}>{labels.get(ident) ?? ident}</span>
      )
    } else if (ws) {
      parts.push(<span key={k++}>{ws}</span>)
    } else {
      // single char: dim the structural punctuation, keep anything else plain.
      parts.push(
        '(){}[],:.'.includes(ch)
          ? <span key={k++} style={{ color: 'var(--text-dim)' }}>{ch}</span>
          : <span key={k++}>{ch}</span>
      )
    }
  }
  return <>{parts}</>
}

// Renders each justification as its ordered list of Manchester axiom lines
// (one reasoning step per line). Uniform across reasoners (whelk, rustdl, …)
// since the reasoner-service renders every justification to Manchester syntax.
// Entity IRIs are shown as clickable labels (from the server `labels` map, with
// the cheap in-memory `labelMap` and an IRI-fragment as fallbacks) and keywords
// are colour-highlighted; see ManchesterLine.
function JustificationDisplay({ justifications, labelMap, labels, slug, vid }: {
  justifications: string[][]
  labelMap?: Map<string, string>
  labels?: Record<string, string>
  slug?: string
  vid?: string
}) {
  // Server labels (real, incl. OBO) take precedence; fall back to the cheap
  // in-memory panel labels for anything the server didn't resolve.
  const merged = new Map<string, string>(labelMap ?? [])
  if (labels) for (const [iri, label] of Object.entries(labels)) merged.set(iri, label)
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
            <div key={j} style={{
              fontSize: 11, lineHeight: 1.7, fontFamily: 'var(--font-mono, monospace)',
              whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: 'var(--text-muted)',
            }}>
              <ManchesterLine line={line} labels={merged} slug={slug} vid={vid} />
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

// Tooltip/disabled styling shared by both "inference" explain toggles.
const NO_JUSTIFY_TITLE = 'This reasoner does not produce explanations'

function InferredClassRow({ c, slug, vid, ontologyId, versionId, termIri, canJustify, labelMap }: {
  c: ClassRef; slug: string; vid: string; ontologyId: string; versionId: string; termIri: string
  canJustify: boolean; labelMap: Map<string, string>
}) {
  const [expanded, setExpanded] = useState(false)
  const { data, isLoading, isError } = useQuery({
    queryKey: ['justification', versionId, termIri, c.iri],
    queryFn: () => api.ontologies.justification(ontologyId, versionId, termIri, c.iri),
    enabled: expanded && canJustify,
    staleTime: 0,
    retry: false,
  })

  return (
    <div style={{ marginBottom: 4 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <ClassBubble c={c} slug={slug} vid={vid} />
        <button
          onClick={() => canJustify && setExpanded(e => !e)}
          disabled={!canJustify}
          title={canJustify ? 'Show justification' : NO_JUSTIFY_TITLE}
          style={{
            fontSize: 9, padding: '1px 4px', borderRadius: 2,
            cursor: canJustify ? 'pointer' : 'not-allowed',
            background: 'none', flexShrink: 0,
            opacity: canJustify ? 1 : 0.5,
            color: expanded ? 'var(--accent)' : 'var(--text-dim)',
            border: `1px solid ${expanded ? 'var(--accent)' : 'var(--border)'}`,
          }}
        >
          inference
        </button>
      </div>
      {expanded && canJustify && (
        <div style={{ marginLeft: 4 }}>
          {isLoading && <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>Computing…</span>}
          {isError && <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>Unavailable</span>}
          {data?.justifications.length === 0 && (
            <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
              {data.timed_out ? 'Still computing — try again' : 'No justification available'}
            </span>
          )}
          {data?.justifications && data.justifications.length > 0 && (
            <JustificationDisplay justifications={data.justifications} labelMap={labelMap}
              labels={data.labels} slug={slug} vid={vid} />
          )}
        </div>
      )}
    </div>
  )
}

function InferredSuperclasses({ items, slug, vid, ontologyId, versionId, termIri, canJustify, labelMap }: {
  items: ClassRef[]; slug: string; vid: string; ontologyId: string; versionId: string; termIri: string
  canJustify: boolean; labelMap: Map<string, string>
}) {
  if (items.length === 0) return null
  const sorted = [...items].sort((a, b) =>
    (a.label || a.iri).localeCompare(b.label || b.iri, undefined, { sensitivity: 'base' })
  )
  return (
    <div style={{ marginBottom: 8 }}>
      {sorted.map(c => (
        <InferredClassRow key={c.iri} c={c} slug={slug} vid={vid}
          ontologyId={ontologyId} versionId={versionId} termIri={termIri}
          canJustify={canJustify} labelMap={labelMap} />
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
    case 'datatype_restriction': {
      // e.g. decimal[>= 0.0, <= 1.0]
      const SYM: Record<string, string> = {
        minInclusive: '≥', maxInclusive: '≤', minExclusive: '>', maxExclusive: '<',
      }
      content = (
        <span>
          <ExprNode node={node.datatype} slug={slug} vid={vid} />
          <span style={{ color: 'var(--text-dim)' }}>[</span>
          {node.facets.map((f, i) => (
            <React.Fragment key={i}>
              {i > 0 && <span style={{ color: 'var(--text-dim)' }}>, </span>}
              <span style={{ color: 'var(--accent-blue)', fontStyle: 'italic' }}>{SYM[f.facet] ?? f.facet}</span>
              {' '}
              <span style={{ color: 'var(--text-muted)' }}>{f.value}</span>
            </React.Fragment>
          ))}
          <span style={{ color: 'var(--text-dim)' }}>]</span>
        </span>
      )
      break
    }
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

function InferredExprRow({ entry, slug, vid, ontologyId, versionId, termIri, canJustify, labelMap }: {
  entry: InferredExprEntry; slug: string; vid: string
  ontologyId: string; versionId: string; termIri: string
  canJustify: boolean; labelMap: Map<string, string>
}) {
  const [expanded, setExpanded] = useState(false)
  const { data, isLoading, isError } = useQuery({
    queryKey: ['justification', versionId, termIri, entry.from_iri],
    queryFn: () => api.ontologies.justification(ontologyId, versionId, termIri, entry.from_iri),
    enabled: expanded && canJustify,
    staleTime: 0,
    retry: false,
  })

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
          onClick={() => canJustify && setExpanded(e => !e)}
          disabled={!canJustify}
          title={canJustify ? 'Show justification' : NO_JUSTIFY_TITLE}
          style={{
            fontSize: 9, padding: '1px 4px', borderRadius: 2,
            cursor: canJustify ? 'pointer' : 'not-allowed',
            background: 'none', flexShrink: 0,
            opacity: canJustify ? 1 : 0.5,
            color: expanded ? 'var(--accent)' : 'var(--text-dim)',
            border: `1px solid ${expanded ? 'var(--accent)' : 'var(--border)'}`,
          }}
        >
          inference
        </button>
      </div>
      {expanded && canJustify && (
        <div style={{ marginLeft: 4 }}>
          {isLoading && <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>Computing…</span>}
          {isError && <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>Unavailable</span>}
          {displayJusts?.length === 0 && (
            <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
              {data?.timed_out ? 'Still computing — try again' : 'No justification available'}
            </span>
          )}
          {displayJusts && displayJusts.length > 0 && (
            <JustificationDisplay justifications={displayJusts} labelMap={labelMap}
              labels={data?.labels} slug={slug} vid={vid} />
          )}
        </div>
      )}
    </div>
  )
}

function InferredExprList({ entries, slug, vid, ontologyId, versionId, termIri, canJustify, labelMap }: {
  entries: InferredExprEntry[]; slug: string; vid: string
  ontologyId: string; versionId: string; termIri: string
  canJustify: boolean; labelMap: Map<string, string>
}) {
  if (entries.length === 0) return null
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginBottom: 8 }}>
      {entries.map((entry, i) => (
        <InferredExprRow key={i} entry={entry} slug={slug} vid={vid}
          ontologyId={ontologyId} versionId={versionId} termIri={termIri}
          canJustify={canJustify} labelMap={labelMap} />
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


// Paged list of a class's asserted individuals (instances). Fetches the first
// page eagerly to decide whether to render the section at all, then pages the
// rest through UsagePager. Hidden entirely when the class has no instances, so
// TBox-only classes show nothing.
const INSTANCES_PAGE = 50

function ClassInstances({ ontologyId, versionId, classIri, slug, lang }: {
  ontologyId: string
  versionId: string
  classIri: string
  slug: string
  lang?: string | null
}) {
  const { data, isLoading } = useQuery({
    queryKey: ['class-instances', ontologyId, versionId, classIri, lang ?? ''],
    queryFn: () => api.ontologies.terms(ontologyId, versionId, classIri, 'individual', false, true, INSTANCES_PAGE, 0, lang),
    staleTime: 60_000,
  })
  if (isLoading) return null
  const first = data?.terms ?? []
  if (first.length === 0) return null

  const more = first.length === INSTANCES_PAGE
  return (
    <Section label={`Instances (${first.length}${more ? '+' : ''})`}>
      <UsagePager<Term>
        key={`${classIri}:${lang ?? ''}`}
        initial={first}
        initialHasMore={more}
        fetchPage={async (offset) => {
          const page = await api.ontologies.terms(ontologyId, versionId, classIri, 'individual', false, true, INSTANCES_PAGE, offset, lang)
          return { items: page.terms, has_more: page.terms.length === INSTANCES_PAGE }
        }}
      >
        {(rows) => (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {rows.map(t => (
              <div key={t.iri} style={{ paddingLeft: 8 }}>
                <IriLink iri={t.iri} label={t.label ?? t.iri.split(/[#/]/).pop() ?? t.iri} slug={slug} vid={versionId} />
              </div>
            ))}
          </div>
        )}
      </UsagePager>
    </Section>
  )
}

// Paged list of a property's direct sub-properties (properties Y where
// `Y subPropertyOf <property>`). Uses the same paginated terms endpoint that
// backs the property tree (parent=<property>, entity_type=<property's type>).
// Hidden when the property has no sub-properties.
function SubPropertyList({ ontologyId, versionId, propertyIri, entityType, slug, lang }: {
  ontologyId: string
  versionId: string
  propertyIri: string
  entityType: 'object_property' | 'data_property' | 'annotation_property' | 'property'
  slug: string
  lang?: string | null
}) {
  const { data, isLoading } = useQuery({
    queryKey: ['subproperties', ontologyId, versionId, propertyIri, entityType, lang ?? ''],
    queryFn: () => api.ontologies.terms(ontologyId, versionId, propertyIri, entityType, false, true, INSTANCES_PAGE, 0, lang),
    staleTime: 60_000,
  })
  if (isLoading) return null
  const first = data?.terms ?? []
  if (first.length === 0) return null

  const more = first.length === INSTANCES_PAGE
  return (
    <Section label={`Sub-properties (${first.length}${more ? '+' : ''})`}>
      <UsagePager<Term>
        key={`${propertyIri}:${lang ?? ''}`}
        initial={first}
        initialHasMore={more}
        fetchPage={async (offset) => {
          const page = await api.ontologies.terms(ontologyId, versionId, propertyIri, entityType, false, true, INSTANCES_PAGE, offset, lang)
          return { items: page.terms, has_more: page.terms.length === INSTANCES_PAGE }
        }}
      >
        {(rows) => (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {rows.map(t => (
              <div key={t.iri} style={{ paddingLeft: 8 }}>
                <IriLink iri={t.iri} label={t.label ?? t.iri.split(/[#/]/).pop() ?? t.iri} slug={slug} vid={versionId} />
              </div>
            ))}
          </div>
        )}
      </UsagePager>
    </Section>
  )
}

// Renders usage entries as Manchester-syntax axiom lines with clickable IRIs.
// One line per axiom, e.g. `Man SubClassOf hasFather some Man`. Used in place of
// the flat Class/Relation/Restriction/Filler tables when the backend supplies
// `manchester` tokens (it always does on current versions; the tables remain as
// a fallback for stale cached responses without tokens).
function UsageManchester({ rows, slug, vid }: {
  rows: { manchester?: ManchesterToken[] | null }[]
  slug: string
  vid: string
}) {
  return (
    <pre style={{
      margin: 0, padding: '0.5rem 0.75rem',
      background: 'var(--bg-secondary)', border: '1px solid var(--border)',
      borderRadius: 4, fontFamily: 'var(--font-mono, ui-monospace, monospace)',
      fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
      overflowX: 'auto',
    }}>
      {rows.map((row, i) => (
        <div key={i}>
          {(row.manchester ?? []).map((tok, j) =>
            tok.t === 'text'
              ? <span key={j}>{tok.v}</span>
              : tok.in_ontology
                ? <IriLink key={j} iri={tok.iri} label={tok.label} slug={slug} vid={vid} />
                : <span key={j} title={tok.iri} style={{ cursor: 'help' }}>{tok.label}</span>
          )}
        </div>
      ))}
    </pre>
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
              {u.filler_expr ? (
                <ExprNode node={u.filler_expr} slug={slug} vid={vid} />
              ) : u.filler_iri ? (
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

// A single predicate's value list, capped so a high-fan-out assertion (e.g. an
// individual linked to thousands of others, or a long sameAs chain) doesn't
// render thousands of DOM nodes at once. Shows the first VALUE_CAP values with
// a "show N more" expander.
const VALUE_CAP = 20

function PropertyValueCell({ values, slug, versionId }: {
  values: { value: string; lang: string | null }[]
  slug: string
  versionId: string
}) {
  const [expanded, setExpanded] = useState(false)
  const shown = expanded ? values : values.slice(0, VALUE_CAP)
  const hiddenCount = values.length - VALUE_CAP
  return (
    <>
      {shown.map((entry, i) => {
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
      {hiddenCount > 0 && (
        <button
          onClick={() => setExpanded(e => !e)}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: 'var(--accent)', fontSize: 11, padding: '2px 0 0 0',
          }}
        >
          {expanded ? 'show less' : `show ${hiddenCount} more`}
        </button>
      )}
    </>
  )
}

// Always-visible table of a fixed set of predicate assertions (e.g. an
// individual's object- or data-property assertions). Unlike AnnotationsSection
// there is NO standardized/original toggle — these are asserted facts, not
// annotations, so they must always be shown.
function AssertionsSection({
  label, properties, preds, propertyLabels, roleMap, slug, versionId, lang,
}: {
  label: string
  properties: Record<string, { value: string; lang: string | null }[]>
  preds: string[]
  propertyLabels: Record<string, string>
  roleMap: Map<string, string>
  slug: string
  versionId: string
  lang?: string | null
}) {
  if (preds.length === 0) return null
  const rows = preds
    .map(pred => ({
      pred,
      values: properties[pred] ?? [],
      displayLabel: resolvePredLabel(pred, 'original', propertyLabels, roleMap),
    }))
    .filter(r => r.values.length > 0)
    .sort((a, b) => a.displayLabel.localeCompare(b.displayLabel))
  if (rows.length === 0) return null

  return (
    <Section label={label}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 'var(--font-size-sm)' }}>
        <tbody>
          {rows.map(({ pred, values, displayLabel }) => {
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
                  <PropertyValueCell values={displayVals} slug={slug} versionId={versionId} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </Section>
  )
}

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
                    <PropertyValueCell values={displayVals} slug={slug} versionId={versionId} />
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
  // Split asserted predicates by their OWL type so object- and data-property
  // assertions (the substantive ABox facts) get their own always-visible
  // sections. Only genuine annotation properties (and unindexed predicates)
  // fall through to AnnotationsSection, whose standardized/original toggle is
  // meant for annotations alone — not relational assertions.
  const objectPreds = Object.keys(data.rawProperties)
    .filter(p => data.propertyTypes[p] === 'object_property' && !HANDLED_PREDICATES.has(p))
  const dataPreds = Object.keys(data.rawProperties)
    .filter(p => data.propertyTypes[p] === 'data_property' && !HANDLED_PREDICATES.has(p))
  const annotationHandled = new Set([...HANDLED_PREDICATES, ...objectPreds, ...dataPreds])

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

      <AssertionsSection
        label="Object property assertions"
        properties={data.rawProperties}
        preds={objectPreds}
        propertyLabels={data.propertyLabels}
        roleMap={roleMap}
        slug={slug} versionId={versionId} lang={lang}
      />

      <AssertionsSection
        label="Data property assertions"
        properties={data.rawProperties}
        preds={dataPreds}
        propertyLabels={data.propertyLabels}
        roleMap={roleMap}
        slug={slug} versionId={versionId} lang={lang}
      />

      <AnnotationsSection
        properties={data.rawProperties}
        propertyLabels={data.propertyLabels}
        handled={annotationHandled}
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

      {/* Direct super-properties (this property subPropertyOf X). subPropertyOf
          is in PROPERTY_HANDLED_PREDICATES (excluded from the annotations table),
          so it is rendered here from the asserted values — mirroring the
          Sub-properties list below. */}
      {(() => {
        const supers = (data.rawProperties['http://www.w3.org/2000/01/rdf-schema#subPropertyOf'] ?? [])
          .map(v => v.value).filter(v => v.startsWith('http'))
        return supers.length > 0 && (
          <Section label={`Super-properties (${supers.length})`}>
            {supers.map(iri => (
              <div key={iri} style={{ paddingLeft: 8, marginBottom: 2 }}>
                <IriLink iri={iri} label={shortLabel(iri)} slug={slug} vid={versionId} />
              </div>
            ))}
          </Section>
        )
      })()}

      {ontologyId && data.entityType !== 'class' && data.entityType !== 'individual' && (
        <SubPropertyList
          ontologyId={ontologyId}
          versionId={versionId}
          propertyIri={data.iri}
          entityType={data.entityType}
          slug={slug}
          lang={lang}
        />
      )}

      {/* Identity/chain axioms in Manchester syntax: equivalentProperty and
          propertyChainAxiom (rendered as `p1 o p2 o …`, incl. `inverse q`
          members). subPropertyOf is shown as Super-properties above.
          Server-supplied token lines. */}
      {data.propertyAxioms.length > 0 && (
        <Section label="Property axioms">
          <UsageManchester
            rows={data.propertyAxioms.map(toks => ({ manchester: toks }))}
            slug={slug} vid={versionId}
          />
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
            rows.length > 0 && rows.every(r => r.manchester)
              ? <UsageManchester rows={rows} slug={slug} vid={versionId} />
              : <UsageTable
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

export default function TermPanel({ ontologyId, versionId, termIri, slug, singlePane = false, lang, versionReasoner }: Props) {
  const { data: baseData, isLoading, error } = useTerm(ontologyId, versionId, termIri, lang)
  // Lazy fetch of the three expensive sections deferred by the backend. Merged
  // into `data` once it arrives so the rendering below doesn't need to branch.
  const { data: expanded } = useTermExpanded(ontologyId, versionId, termIri, lang)
  // Profile + meta fetched at the panel level so the role map can be shared
  // between the header (deprecation chip) and the Annotations section.
  const { data: profile } = useOntologyProfile(ontologyId ?? undefined, versionId)
  const { data: meta }    = useOntologyMeta(ontologyId ?? undefined, versionId)
  const roleMap = buildRoleMap(profile, meta)

  // Reasoner capability lookup — rarely changes, so cached long. Drives
  // whether the "inference" explain buttons below are enabled: a reasoner
  // that can't produce explanations (e.g. konclude) gets a disabled button
  // with a tooltip instead of a broken/empty explain flow.
  const { data: reasonersData } = useQuery({
    queryKey: ['reasoners'],
    queryFn: () => api.reasoners.list(),
    staleTime: 5 * 60_000,
  })
  const reasonerInfo = versionReasoner ? reasonersData?.find(r => r.name === versionReasoner) : undefined
  // Unknown reasoner (not yet loaded, or not found in the list) defaults to
  // enabled — only a confirmed missing `justify` capability disables it.
  const canJustify = !reasonerInfo || reasonerInfo.capabilities.includes('justify')

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
  // Only the class body's inferred-superclass/disjointWith sections render
  // justification explain buttons, so the label map is only built there.
  const justificationLabelMap = buildJustificationLabelMap(data)

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
              ontologyId={ontologyId} versionId={versionId} termIri={termIri}
              canJustify={canJustify} labelMap={justificationLabelMap} />
            <ClassExprList
              exprs={data.superclassExpressions ?? []}
              slug={slug} vid={versionId}
            />
            <InferredExprList
              entries={data.inferredSuperclassExpressions ?? []}
              slug={slug} vid={versionId}
              ontologyId={ontologyId} versionId={versionId} termIri={termIri}
              canJustify={canJustify} labelMap={justificationLabelMap}
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
              canJustify={canJustify} labelMap={justificationLabelMap} />
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

        {ontologyId && (
          <ClassInstances
            ontologyId={ontologyId}
            versionId={versionId}
            classIri={data.iri}
            slug={slug}
            lang={lang}
          />
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
                rows.length > 0 && rows.every(r => r.manchester)
                  ? <UsageManchester rows={rows} slug={slug} vid={versionId} />
                  : <ClassUsageTable
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
