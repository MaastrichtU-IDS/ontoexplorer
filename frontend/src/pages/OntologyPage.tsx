import { useState, useEffect, useRef } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useOntologies } from '../hooks/useOntologies'
import { useVersions } from '../hooks/useVersions'
import { useTerm } from '../hooks/useTerm'
import { slugFromIri, OntologyVersion, OntologyMetadataEntry, SearchResult, api } from '../lib/api'
import ClassTree from '../components/ClassTree'
import TermPanel from '../components/TermPanel'
import ResizeHandle from '../components/ResizeHandle'

const PANE_MIN = 220
const PANE_MAX = 640
const PANE_DEFAULT = 300

// ── Mobile detection ──────────────────────────────────────────────────────────

function useIsMobile(breakpoint = 768) {
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < breakpoint)
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${breakpoint - 1}px)`)
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [breakpoint])
  return isMobile
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function MetaRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <tr>
      <td style={{
        padding: '6px 0', verticalAlign: 'top',
        color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)',
        whiteSpace: 'nowrap', paddingRight: 20, width: 1,
      }}>
        {label}
      </td>
      <td style={{ padding: '6px 0', color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)', wordBreak: 'break-all' }}>
        {children}
      </td>
    </tr>
  )
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div style={{
      background: 'var(--bg-secondary)', border: '1px solid var(--border)',
      borderRadius: 'var(--radius)', padding: '10px 14px', flex: '1 1 100px', minWidth: 0,
    }}>
      <div style={{ color: 'var(--text)', fontSize: 18, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
        {typeof value === 'number' ? value.toLocaleString() : value}
      </div>
      <div style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: 2 }}>{label}</div>
    </div>
  )
}

// ── Predicate label map ───────────────────────────────────────────────────────

const PRED_LABELS: Record<string, string> = {
  // Identity
  'http://www.w3.org/2000/01/rdf-schema#label':              'Label',
  'http://purl.org/dc/terms/title':                          'Title',
  'http://purl.org/dc/elements/1.1/title':                   'Title',
  'http://purl.org/dc/terms/alternative':                    'Alternative Title',
  // Description
  'http://www.w3.org/2000/01/rdf-schema#comment':            'Comment',
  'http://purl.org/dc/terms/description':                    'Description',
  'http://purl.org/dc/elements/1.1/description':             'Description',
  // Status & dates
  'https://w3id.org/mod#status':                             'Status',
  'http://purl.org/dc/terms/created':                        'Created',
  'http://purl.org/dc/terms/modified':                       'Modified',
  'http://purl.org/dc/terms/issued':                         'Issued',
  // Agents
  'http://purl.org/dc/terms/creator':                        'Creator',
  'http://purl.org/dc/elements/1.1/creator':                 'Creator',
  'http://purl.org/pav/authoredBy':                          'Authored By',
  'http://purl.org/dc/terms/contributor':                    'Contributor',
  'http://purl.org/dc/terms/publisher':                      'Publisher',
  // Version
  'http://www.w3.org/2002/07/owl#versionInfo':               'Version Info',
  'http://purl.org/pav/version':                             'PAV Version',
  'http://www.w3.org/2002/07/owl#versionIRI':                'Version IRI',
  // Web presence
  'http://xmlns.com/foaf/0.1/homepage':                      'Homepage',
  'http://xmlns.com/foaf/0.1/page':                          'Page',
  'http://www.w3.org/ns/dcat#accessURL':                     'Access URL',
  'https://schema.org/includedInDataCatalog':                'In Catalog',
  'https://schema.org/funding':                              'Funding',
  // MOD structural metadata
  'https://w3id.org/mod#prefLabelProperty':                  'Pref Label Property',
  'https://w3id.org/mod#definitionProperty':                 'Definition Property',
  'https://w3id.org/mod#hasRepresentationLanguage':          'Representation Language',
  'https://w3id.org/mod#hasSyntax':                          'Syntax',
  // Secondary
  'http://purl.org/dc/terms/language':                       'Language',
  'http://purl.org/dc/terms/license':                        'License',
  'http://purl.org/dc/terms/rights':                         'Rights',
  'http://purl.org/dc/terms/subject':                        'Subject',
  'http://purl.org/dc/terms/source':                         'Source',
  'http://purl.org/dc/terms/bibliographicCitation':          'Citation',
  'http://purl.org/vocab/vann/preferredNamespacePrefix':     'Namespace Prefix',
  'http://purl.org/vocab/vann/preferredNamespaceUri':        'Namespace URI',
  'http://www.w3.org/2002/07/owl#priorVersion':              'Prior Version',
  'http://www.w3.org/2002/07/owl#backwardCompatibleWith':    'Backward Compatible With',
  'http://www.w3.org/2002/07/owl#incompatibleWith':          'Incompatible With',
  'http://omv.ontoware.org/2005/05/ontology#acronym':        'Acronym',
  'http://xmlns.com/foaf/0.1/fundedBy':                      'Funded By',
}

// Display order — predicates not listed here are appended alphabetically by label
const PRED_ORDER: string[] = [
  'http://www.w3.org/2000/01/rdf-schema#label',
  'http://purl.org/dc/terms/title',
  'http://purl.org/dc/elements/1.1/title',
  'http://purl.org/dc/terms/alternative',
  'http://purl.org/dc/terms/description',
  'http://purl.org/dc/elements/1.1/description',
  'http://www.w3.org/2000/01/rdf-schema#comment',
  'http://purl.org/dc/terms/language',
  'https://w3id.org/mod#status',
  'http://purl.org/dc/terms/created',
  'http://purl.org/dc/terms/modified',
  'http://purl.org/dc/terms/issued',
  'http://purl.org/dc/terms/creator',
  'http://purl.org/dc/elements/1.1/creator',
  'http://purl.org/pav/authoredBy',
  'http://purl.org/dc/terms/contributor',
  'http://purl.org/dc/terms/publisher',
  'http://www.w3.org/2002/07/owl#versionInfo',
  'http://purl.org/pav/version',
  'http://www.w3.org/2002/07/owl#versionIRI',
  'http://www.w3.org/2002/07/owl#priorVersion',
  'http://www.w3.org/2002/07/owl#backwardCompatibleWith',
  'http://xmlns.com/foaf/0.1/homepage',
  'http://xmlns.com/foaf/0.1/page',
  'http://www.w3.org/ns/dcat#accessURL',
  'https://schema.org/includedInDataCatalog',
  'http://purl.org/dc/terms/license',
  'https://schema.org/funding',
  'http://purl.org/dc/terms/bibliographicCitation',
  'https://w3id.org/mod#prefLabelProperty',
  'https://w3id.org/mod#definitionProperty',
  'https://w3id.org/mod#hasRepresentationLanguage',
  'https://w3id.org/mod#hasSyntax',
]

function predLabel(iri: string): string {
  if (PRED_LABELS[iri]) return PRED_LABELS[iri]
  const frag = iri.replace(/[/#]+$/, '')
  return frag.includes('#') ? frag.split('#').pop()! : frag.split('/').pop()!
}

function MetaValue({ entry }: { entry: OntologyMetadataEntry }) {
  if (entry.type === 'iri') {
    const display = entry.value.length > 80 ? entry.value.slice(0, 77) + '…' : entry.value
    if (entry.value.startsWith('http://') || entry.value.startsWith('https://')) {
      return (
        <a href={entry.value} target="_blank" rel="noreferrer"
          style={{ color: 'var(--accent)', wordBreak: 'break-all' }}>
          {display} ↗
        </a>
      )
    }
    return <span style={{ wordBreak: 'break-all' }}>{entry.value}</span>
  }
  return (
    <span style={{ wordBreak: 'break-word' }}>
      {entry.value}
      {entry.language && (
        <span style={{ marginLeft: 4, fontSize: 10, color: 'var(--text-dim)', fontStyle: 'italic' }}>
          @{entry.language}
        </span>
      )}
    </span>
  )
}

const SKIP_PREDICATES = new Set([
  'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
  'http://www.w3.org/2002/07/owl#imports',
])

function OntologyDocMeta({ ontologyId, versionId }: { ontologyId: string; versionId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['onto-doc-meta', ontologyId, versionId],
    queryFn: () => api.ontologies.ontologyMetadata(ontologyId, versionId),
    staleTime: 300_000,
  })

  const predicates = data?.predicates ?? {}
  const entries = Object.entries(predicates)
    .filter(([p]) => !SKIP_PREDICATES.has(p))
    .sort(([a], [b]) => {
      const ai = PRED_ORDER.indexOf(a)
      const bi = PRED_ORDER.indexOf(b)
      if (ai !== -1 && bi !== -1) return ai - bi
      if (ai !== -1) return -1
      if (bi !== -1) return 1
      return predLabel(a).localeCompare(predLabel(b))
    })

  if (isLoading) {
    return <div style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>Loading metadata…</div>
  }

  if (entries.length === 0) {
    return (
      <div style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', fontStyle: 'italic' }}>
        No ontology-level metadata found in document.
      </div>
    )
  }

  return (
    <table style={{ borderCollapse: 'collapse', width: '100%' }}>
      <tbody>
        {entries.map(([pred, values]) => (
          <tr key={pred}>
            <td style={{
              padding: '5px 0', verticalAlign: 'top',
              color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)',
              whiteSpace: 'nowrap', paddingRight: 20, width: 1,
            }}>
              {predLabel(pred)}
            </td>
            <td style={{ padding: '5px 0', fontSize: 'var(--font-size-sm)', color: 'var(--text-muted)' }}>
              {values.map((v, i) => (
                <div key={i} style={{ marginBottom: values.length > 1 ? 2 : 0 }}>
                  <MetaValue entry={v} />
                </div>
              ))}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// ── Metadata + stats panel ────────────────────────────────────────────────────

function OntologyMeta({ iri, version }: { iri: string; version: OntologyVersion | undefined }) {
  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['version-stats', version?.ontology_id, version?.id],
    queryFn: () => api.ontologies.stats(version!.ontology_id, version!.id),
    enabled: !!version,
    staleTime: 120_000,
  })

  if (!version) {
    return <div style={{ padding: '2rem', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>Loading…</div>
  }

  const statusColor = version.status === 'ingested' ? '#50c878' : 'var(--text-dim)'

  return (
    <div style={{ padding: '1.5rem 2rem', overflow: 'auto', flex: 1 }}>

      {/* ── Statistics ── */}
      <h3 style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12 }}>
        Statistics
      </h3>
      {statsLoading ? (
        <div style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>Loading stats…</div>
      ) : stats ? (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 28 }}>
          <StatCard label="Axioms" value={stats.triple_count} />
          <StatCard label="Classes" value={stats.class_count} />
          <StatCard label="Object Properties" value={stats.object_property_count} />
          <StatCard label="Datatype Properties" value={stats.datatype_property_count} />
          <StatCard label="Annotation Properties" value={stats.annotation_property_count} />
          {stats.individual_count > 0 && (
            <StatCard label="Individuals" value={stats.individual_count} />
          )}
        </div>
      ) : null}

      {/* ── Document metadata ── */}
      <h3 style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12 }}>
        Document Metadata
      </h3>
      <div style={{ marginBottom: 28 }}>
        <OntologyDocMeta ontologyId={version.ontology_id} versionId={version.id} />
      </div>

      {/* ── Repository metadata ── */}
      <h3 style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12 }}>
        Repository
      </h3>
      <table style={{ borderCollapse: 'collapse', width: '100%', marginBottom: 28 }}>
        <tbody>
          <MetaRow label="Ontology IRI">{iri}</MetaRow>
          {version.version_iri && <MetaRow label="Version IRI">{version.version_iri}</MetaRow>}
          <MetaRow label="Format">{version.format?.toUpperCase() ?? '—'}</MetaRow>
          <MetaRow label="Status">
            <span style={{
              fontSize: 11,
              background: version.status === 'ingested' ? 'rgba(80,200,120,0.12)' : 'var(--bg-secondary)',
              color: statusColor, borderRadius: 3, padding: '1px 7px',
            }}>
              {version.status}
            </span>
          </MetaRow>
          <MetaRow label="Ingested">{new Date(version.created_at).toLocaleString()}</MetaRow>
          <MetaRow label="SHA-256">{version.sha256.slice(0, 16) + '…'}</MetaRow>
          {version.download_url && (
            <MetaRow label="Download">
              <a href={version.download_url} style={{ color: 'var(--accent)' }} target="_blank" rel="noreferrer">
                Download file ↗
              </a>
            </MetaRow>
          )}
        </tbody>
      </table>
    </div>
  )
}

// ── Collapsible section ───────────────────────────────────────────────────────

function ExpandToggleBtn({ onExpand, onCollapse }: { onExpand: () => void; onCollapse: () => void }) {
  const [expanded, setExpanded] = useState(false)
  function handleClick() {
    if (expanded) { onCollapse() } else { onExpand() }
    setExpanded(v => !v)
  }
  return (
    <button
      onClick={handleClick}
      style={{
        fontSize: 9, padding: '2px 6px', borderRadius: 3,
        border: '1px solid var(--border)', background: 'none',
        color: 'var(--text-dim)', cursor: 'pointer',
        textTransform: 'uppercase', letterSpacing: 0.5,
      }}
      onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--text-muted)' }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)' }}
    >
      {expanded ? 'Collapse' : 'Expand'}
    </button>
  )
}

function CollapsibleSection({ label, defaultOpen = true, children }: {
  label: string; defaultOpen?: boolean; children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div style={{ borderBottom: '1px solid var(--border)' }}>
      <button
        onClick={() => setOpen(v => !v)}
        style={{
          width: '100%', textAlign: 'left',
          padding: '7px 10px', display: 'flex', alignItems: 'center', gap: 6,
          background: 'none', border: 'none', cursor: 'pointer',
          color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 1,
        }}
      >
        <span style={{ fontSize: 9, flexShrink: 0 }}>{open ? '▾' : '▸'}</span>
        {label}
      </button>
      {open && children}
    </div>
  )
}

// ── Ontology search bar ───────────────────────────────────────────────────────

function useDebounce<T>(value: T, ms: number): T {
  const [d, setD] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setD(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return d
}

function OntologySearchBar({
  ontologyId, versionId, onSelect,
}: { ontologyId: string; versionId: string; onSelect: (iri: string) => void }) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [activeIdx, setActiveIdx] = useState(-1)
  const dq = useDebounce(query, 200)
  const containerRef = useRef<HTMLDivElement>(null)

  const { data } = useQuery({
    queryKey: ['onto-search', ontologyId, versionId, dq],
    queryFn: () => api.ontologies.search(ontologyId, versionId, dq),
    enabled: dq.length >= 2,
    staleTime: 30_000,
  })

  const results: SearchResult[] = data?.results ?? []

  useEffect(() => { setActiveIdx(-1) }, [results])

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  function pick(r: SearchResult) {
    onSelect(r.iri); setQuery(''); setOpen(false)
  }

  function handleKey(e: React.KeyboardEvent) {
    if (!open || results.length === 0) return
    if (e.key === 'ArrowDown') { e.preventDefault(); setActiveIdx(i => Math.min(i + 1, results.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActiveIdx(i => Math.max(i - 1, 0)) }
    else if (e.key === 'Enter' && activeIdx >= 0) { e.preventDefault(); pick(results[activeIdx]) }
    else if (e.key === 'Escape') { setOpen(false) }
  }

  return (
    <div ref={containerRef} style={{ position: 'relative', padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>
      <input
        value={query}
        onChange={e => { setQuery(e.target.value); setOpen(true) }}
        onFocus={() => { if (query) setOpen(true) }}
        onKeyDown={handleKey}
        placeholder="Search classes & properties…"
        style={{
          width: '100%', boxSizing: 'border-box',
          padding: '5px 8px', fontSize: 'var(--font-size-sm)',
          background: 'var(--bg)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)', color: 'var(--text)',
          outline: 'none',
        }}
      />
      {open && results.length > 0 && (
        <ul style={{
          position: 'absolute', top: '100%', left: 8, right: 8,
          zIndex: 100, listStyle: 'none', margin: 0, padding: 0,
          background: 'var(--bg-secondary)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)', boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
          maxHeight: 260, overflowY: 'auto',
        }}>
          {results.map((r, i) => (
            <li
              key={r.iri}
              onMouseDown={() => pick(r)}
              onMouseEnter={() => setActiveIdx(i)}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '5px 10px', cursor: 'pointer', fontSize: 'var(--font-size-sm)',
                background: i === activeIdx ? 'var(--bg-hover)' : 'transparent',
                color: 'var(--text)',
              }}
            >
              <span style={{
                fontSize: 9, fontWeight: 700, padding: '1px 4px',
                borderRadius: 3, background: 'var(--bg)', color: 'var(--text-dim)',
                flexShrink: 0,
              }}>
                {r.short}
              </span>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {r.label}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

type HierarchyMode = 'asserted' | 'inferred'

// ── Main page ─────────────────────────────────────────────────────────────────

export default function OntologyPage() {
  const { slug, version } = useParams<{ slug: string; version?: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const isMobile = useIsMobile()
  const { ontologies, isLoading: ontologiesLoading } = useOntologies()

  const ontology = ontologies.find(o => slugFromIri(o.iri) === slug)
  const { data: versionsData, isLoading: versionsLoading } = useVersions(ontology?.id)
  const versions = versionsData?.versions ?? []

  const activeVersion = version
    ? versions.find(v => v.id === version) ?? versions[0]
    : versions[0]
  const activeVid = activeVersion?.id
  const oid = ontology?.id

  const selectedTermIri = searchParams.get('term')
  const [classMode, setClassMode] = useState<HierarchyMode>('asserted')
  const [mobilePane, setMobilePane] = useState<'tree' | 'detail'>('tree')

  const [hideInverseProps, setHideInverseProps] = useState(true)
  const [classExpand,   setClassExpand]   = useState(0)
  const [classCollapse, setClassCollapse] = useState(0)
  const [objExpand,     setObjExpand]     = useState(0)
  const [objCollapse,   setObjCollapse]   = useState(0)
  const [dataExpand,    setDataExpand]    = useState(0)
  const [dataCollapse,  setDataCollapse]  = useState(0)

  // Auto-reveal inverses when navigating to a term that is itself an inverse target
  const { data: selectedTermData } = useTerm(oid ?? null, activeVid ?? null, selectedTermIri)
  useEffect(() => {
    if (selectedTermData?.isInverseTarget && hideInverseProps) {
      setHideInverseProps(false)
    }
  }, [selectedTermData?.isInverseTarget, selectedTermData?.iri])

  const [paneWidth, setPaneWidth] = useState<number>(() => {
    const stored = localStorage.getItem('onto-pane-width')
    return stored ? Number(stored) : PANE_DEFAULT
  })

  function handleDelta(delta: number) {
    setPaneWidth(w => {
      const next = Math.min(PANE_MAX, Math.max(PANE_MIN, w + delta))
      localStorage.setItem('onto-pane-width', String(next))
      return next
    })
  }

  function selectTerm(iri: string) {
    setSearchParams({ term: iri })
    if (isMobile) setMobilePane('detail')
  }

  function resetToMeta() {
    setSearchParams({})
    if (isMobile) setMobilePane('detail')
  }

  if (!ontologiesLoading && !ontology) {
    return (
      <div style={{ padding: '2rem', color: 'var(--text-dim)' }}>
        Ontology <code style={{ color: 'var(--accent)' }}>{slug}</code> not found.
      </div>
    )
  }

  // ── Shared tree pane content ──────────────────────────────────────────────

  const treePaneContent = (
    <>
      {/* Ontology name / back-to-meta */}
      <div style={{ padding: '10px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 8 }}>
        <button
          onClick={resetToMeta}
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0,
            color: 'var(--accent)', fontWeight: 600, fontSize: 'var(--font-size-sm)', textAlign: 'left', flex: 1 }}
        >
          {slug}
        </button>
      </div>

      {/* Search bar */}
      {oid && activeVid && (
        <OntologySearchBar ontologyId={oid} versionId={activeVid} onSelect={selectTerm} />
      )}

      {/* Version selector */}
      {versions.length > 1 && (
        <div style={{ padding: '6px 10px', borderBottom: '1px solid var(--border)' }}>
          <select
            value={activeVid ?? ''}
            onChange={e => navigate(`/ontologies/${slug}/${e.target.value}`, { replace: true })}
            style={{ width: '100%', fontSize: 'var(--font-size-sm)' }}
          >
            {versions.map(v => (
              <option key={v.id} value={v.id}>{v.version_iri ?? v.id}</option>
            ))}
          </select>
        </div>
      )}

      {/* Hierarchy */}
      {oid && activeVid ? (
        <div style={{ flex: 1, overflow: 'auto' }}>
          <div style={{ borderBottom: '1px solid var(--border)' }}>
            <div style={{ padding: '5px 10px', display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 1, flex: 1 }}>
                Classes
              </span>
              <ExpandToggleBtn
                onExpand={() => setClassExpand(v => v + 1)}
                onCollapse={() => setClassCollapse(v => v + 1)}
              />
              <div style={{ display: 'flex', borderRadius: 4, overflow: 'hidden', border: '1px solid var(--border)' }}>
                {(['asserted', 'inferred'] as HierarchyMode[]).map(m => (
                  <button
                    key={m}
                    onClick={() => setClassMode(m)}
                    style={{
                      padding: '2px 8px', fontSize: 10, border: 'none', cursor: 'pointer',
                      background: classMode === m ? 'var(--accent)' : 'transparent',
                      color: classMode === m ? '#000' : 'var(--text-dim)',
                      textTransform: 'capitalize',
                    }}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>
            <ClassTree
              ontologyId={oid} versionId={activeVid}
              selectedIri={selectedTermIri} onSelect={selectTerm}
              entityType="class" mode={classMode} revealIri={selectedTermIri}
              expandSignal={classExpand} collapseSignal={classCollapse}
            />
          </div>
          <CollapsibleSection label="Object Properties" defaultOpen={true}>
            <div style={{ padding: '4px 10px 2px', display: 'flex', alignItems: 'center', gap: 6 }}>
              <ExpandToggleBtn
                onExpand={() => setObjExpand(v => v + 1)}
                onCollapse={() => setObjCollapse(v => v + 1)}
              />
              <button
                onClick={() => setHideInverseProps(v => !v)}
                style={{
                  fontSize: 9, padding: '2px 6px', borderRadius: 3,
                  border: '1px solid var(--border)', background: 'none',
                  color: 'var(--text-dim)', cursor: 'pointer',
                  textTransform: 'uppercase', letterSpacing: 0.5,
                }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--text-muted)' }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)' }}
              >
                {hideInverseProps ? 'Show Inv' : 'Hide Inv'}
              </button>
            </div>
            <ClassTree
              ontologyId={oid} versionId={activeVid}
              selectedIri={selectedTermIri} onSelect={selectTerm}
              entityType="object_property" revealIri={selectedTermIri}
              hideInverse={hideInverseProps}
              expandSignal={objExpand} collapseSignal={objCollapse}
            />
          </CollapsibleSection>
          <CollapsibleSection label="Data Properties" defaultOpen={true}>
            <div style={{ padding: '4px 10px 2px' }}>
              <ExpandToggleBtn
                onExpand={() => setDataExpand(v => v + 1)}
                onCollapse={() => setDataCollapse(v => v + 1)}
              />
            </div>
            <ClassTree
              ontologyId={oid} versionId={activeVid}
              selectedIri={selectedTermIri} onSelect={selectTerm}
              entityType="data_property" revealIri={selectedTermIri}
              expandSignal={dataExpand} collapseSignal={dataCollapse}
            />
          </CollapsibleSection>
          <CollapsibleSection label="Annotation Properties" defaultOpen={false}>
            <ClassTree
              ontologyId={oid} versionId={activeVid}
              selectedIri={selectedTermIri} onSelect={selectTerm}
              entityType="annotation_property" revealIri={selectedTermIri}
            />
          </CollapsibleSection>
        </div>
      ) : (
        <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
          {versionsLoading ? 'Loading…' : 'No versions available'}
        </div>
      )}
    </>
  )

  // ── Shared detail pane content ────────────────────────────────────────────

  const detailPaneContent = (
    <>
      {/* Mobile top bar: back button */}
      {isMobile && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '8px 12px', borderBottom: '1px solid var(--border)',
          background: 'var(--bg-secondary)', flexShrink: 0,
        }}>
          <button
            onClick={() => setMobilePane('tree')}
            style={{
              display: 'flex', alignItems: 'center', gap: 4,
              fontSize: 'var(--font-size-sm)', color: 'var(--accent)',
              background: 'none', border: 'none', cursor: 'pointer', padding: 0,
            }}
          >
            ← Browse
          </button>
          <span style={{ color: 'var(--border)' }}>|</span>
          <span style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {selectedTermIri
              ? (selectedTermIri.split(/[#/]/).pop() ?? selectedTermIri)
              : slug}
          </span>
        </div>
      )}
      {oid && activeVid && selectedTermIri ? (
        <TermPanel
          ontologyId={oid} versionId={activeVid}
          termIri={selectedTermIri} slug={slug!} singlePane={true}
        />
      ) : (
        <OntologyMeta iri={ontology?.iri ?? ''} version={activeVersion} />
      )}
    </>
  )

  // ── Mobile layout: one pane at a time ─────────────────────────────────────

  if (isMobile) {
    return (
      <div style={{ height: 'calc(100vh - var(--nav-height))', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {mobilePane === 'tree' ? (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--bg-secondary)' }}>
            {treePaneContent}
          </div>
        ) : (
          <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            {detailPaneContent}
          </div>
        )}
      </div>
    )
  }

  // ── Desktop layout: side-by-side ──────────────────────────────────────────

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - var(--nav-height))', overflow: 'hidden' }}>
      <div style={{
        width: paneWidth, flexShrink: 0, display: 'flex', flexDirection: 'column',
        background: 'var(--bg-secondary)', borderRight: '1px solid var(--border)', overflow: 'hidden',
      }}>
        {treePaneContent}
      </div>
      <ResizeHandle onDelta={handleDelta} />
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {detailPaneContent}
      </div>
    </div>
  )
}
