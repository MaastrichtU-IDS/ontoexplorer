import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTerm } from '../hooks/useTerm'
import { ClassRef, PropertyUsage } from '../lib/api'
import SourceBadge from './SourceBadge'

function CopyChip({ text, title }: { text: string; title?: string }) {
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
      {copied ? '✓' : '⎘'} {text}
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
      style={{
        display: 'inline-block',
        fontSize: 12, padding: '3px 10px',
        borderRadius: 12,
        background: 'var(--bg)', border: '1px solid var(--border)',
        color: 'var(--accent)', textDecoration: 'none',
        whiteSpace: 'nowrap',
        transition: 'border-color 0.1s',
      }}
      onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--accent)')}
      onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--border)')}
    >
      {c.label}
    </Link>
  )
}

function HierGroup({ label, items, slug, vid, badge }: {
  label: string; items: ClassRef[]; slug: string; vid: string; badge?: string
}) {
  if (items.length === 0) return null
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 5 }}>
        <span style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5 }}>{label}</span>
        {badge && (
          <span style={{ fontSize: 9, background: 'var(--bg)', color: 'var(--text-dim)', borderRadius: 2, padding: '1px 4px' }}>
            {badge}
          </span>
        )}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {items.map(c => <ClassBubble key={c.iri} c={c} slug={slug} vid={vid} />)}
      </div>
    </div>
  )
}

function ClassExprList({ exprs, label }: { exprs: string[]; label?: string }) {
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
          <code key={i} style={{
            fontSize: 11, padding: '3px 8px', borderRadius: 'var(--radius-sm)',
            background: 'var(--bg)', border: '1px solid var(--border)',
            color: 'var(--text-muted)', wordBreak: 'break-word', display: 'block',
          }}>
            {expr}
          </code>
        ))}
      </div>
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

  const typeColor = data.entityType === 'class' ? 'var(--accent-purple)'
    : isProperty ? 'var(--accent-blue)' : 'var(--text-muted)'

  const typeLabel = data.entityType === 'class' ? 'class'
    : data.entityType === 'object_property' ? 'object property'
    : data.entityType === 'data_property' ? 'data property'
    : data.entityType === 'annotation_property' ? 'annotation property'
    : data.entityType === 'property' ? 'property'
    : data.entityType

  const hasSuperclasses = data.superclasses.asserted.length > 0 || data.superclasses.inferred.length > 0
    || (data.superclassExpressions?.length ?? 0) > 0
  const hasSubclasses   = data.subclasses.asserted.length > 0   || data.subclasses.inferred.length > 0

  let body: React.ReactNode

  if (isProperty) {
    body = <PropertyBody data={data} slug={slug} versionId={versionId} />
  } else if (singlePane) {
    body = (
      <div style={{ flex: 1, padding: '10px 16px', overflow: 'auto' }}>
        {data.definition && (
          <p style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', marginBottom: 14, lineHeight: 1.6 }}>
            {data.definition}
          </p>
        )}
        {(data.synonyms.exact.length > 0 || data.synonyms.related.length > 0) && (
          <Section label="Synonyms">
            <div style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)' }}>
              {[...data.synonyms.exact, ...data.synonyms.related].join(' · ')}
            </div>
          </Section>
        )}
        {hasSuperclasses && (
          <Section label="Superclasses">
            <HierGroup label="asserted" items={data.superclasses.asserted} slug={slug} vid={versionId} />
            <HierGroup label="inferred" items={data.superclasses.inferred} slug={slug} vid={versionId} badge="ELK" />
            <ClassExprList exprs={data.superclassExpressions ?? []} label={data.superclasses.asserted.length > 0 || data.superclasses.inferred.length > 0 ? 'expressions' : undefined} />
          </Section>
        )}
        <Section label="Subclasses">
          {hasSubclasses ? (
            <>
              <HierGroup label="asserted" items={data.subclasses.asserted} slug={slug} vid={versionId} />
              <HierGroup label="inferred" items={data.subclasses.inferred} slug={slug} vid={versionId} badge="ELK" />
            </>
          ) : (
            <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>No subclasses</span>
          )}
        </Section>
      </div>
    )
  } else {
    body = (
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <div style={{ flex: 1, padding: '10px 12px', overflow: 'auto', borderRight: '1px solid var(--border)' }}>
          {data.definition && (
            <p style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', marginBottom: 10, lineHeight: 1.5 }}>
              {data.definition}
            </p>
          )}
          {hasSuperclasses && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', marginBottom: 4 }}>Superclasses</div>
              <HierGroup label="asserted" items={data.superclasses.asserted} slug={slug} vid={versionId} />
              <HierGroup label="inferred" items={data.superclasses.inferred} slug={slug} vid={versionId} badge="ELK" />
              <ClassExprList exprs={data.superclassExpressions ?? []} label={data.superclasses.asserted.length > 0 || data.superclasses.inferred.length > 0 ? 'expressions' : undefined} />
            </div>
          )}
          {(data.synonyms.exact.length > 0 || data.synonyms.related.length > 0) && (
            <div>
              <div style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', marginBottom: 4 }}>Synonyms</div>
              <div style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)' }}>
                {[...data.synonyms.exact, ...data.synonyms.related].join(' · ')}
              </div>
            </div>
          )}
        </div>
        <div style={{ flex: 1, padding: '10px 12px', overflow: 'auto' }}>
          <div style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', marginBottom: 6 }}>Subclasses</div>
          {hasSubclasses ? (
            <>
              <HierGroup label="asserted" items={data.subclasses.asserted} slug={slug} vid={versionId} />
              <HierGroup label="inferred" items={data.subclasses.inferred} slug={slug} vid={versionId} badge="ELK" />
            </>
          ) : (
            <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>No subclasses</span>
          )}
        </div>
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
        <CopyChip text={data.iri} />
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
