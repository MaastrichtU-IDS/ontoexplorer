import { useState, useEffect, useRef } from 'react'
import { useNavigate, useParams, useSearchParams, useLocation } from 'react-router-dom'
import { useQuery, useInfiniteQuery } from '@tanstack/react-query'
import { useOntologies } from '../hooks/useOntologies'
import { useVersions } from '../hooks/useVersions'
import { useTerm } from '../hooks/useTerm'
import { useIsMobile } from '../hooks/useIsMobile'
import { slugFromIri, OntologyVersion, OntologyMetadataEntry, SearchResult, Term, api } from '../lib/api'
import ClassTree from '../components/ClassTree'
import TermPanel from '../components/TermPanel'
import IncrementalReasoningPanel from '../components/IncrementalReasoningPanel'
import ResizeHandle from '../components/ResizeHandle'
import ProfileEditor from '../components/ProfileEditor'
import MetaProfileEditor from '../components/MetaProfileEditor'
import HistoryTab from '../components/HistoryTab'
import CoverageSection from '../components/CoverageSection'
import OwlProfileSection from '../components/OwlProfileSection'
import { ReuseSection } from '../components/ReuseSection'
import SearchBar from '../components/SearchBar'
import { useLang } from '../hooks/useLang'
import { useOntologyLanguages } from '../hooks/useOntologyLanguages'
import LanguagePicker from '../components/LanguagePicker'
import { useOntologyMeta } from '../hooks/useOntologyMeta'

const IND_PAGE_SIZE = 50

// Ontology ids already view-beaconed this SPA session — guards against React
// re-renders / StrictMode double-invoke refiring the beacon. The server also
// dedups per visitor per day, so this is just politeness, not correctness.
const _viewedBeacons = new Set<string>()

function IndividualList({ ontologyId, versionId, selectedIri, onSelect, lang }: {
  ontologyId: string
  versionId: string
  selectedIri: string | null
  onSelect: (iri: string) => void
  lang?: string | null
}) {
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } = useInfiniteQuery({
    queryKey: ['individuals', ontologyId, versionId, lang ?? ''],
    queryFn: ({ pageParam = 0 }) =>
      api.ontologies.terms(ontologyId, versionId, null, 'individual', false, true, IND_PAGE_SIZE, pageParam as number, lang),
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.terms.length, 0)
      return last.terms.length === IND_PAGE_SIZE ? loaded : undefined
    },
    initialPageParam: 0,
    staleTime: 60_000,
  })

  const terms: Term[] = data?.pages.flatMap(p => p.terms) ?? []

  // Reveal the selected individual (e.g. arrived from a global search result):
  // keep loading pages until it's found, then scroll it into view. Without this
  // a selected individual on a later page would never render or highlight.
  const selectedRef = useRef<HTMLDivElement | null>(null)
  const selectedLoaded = !!selectedIri && terms.some(t => t.iri === selectedIri)
  useEffect(() => {
    if (selectedIri && !selectedLoaded && hasNextPage && !isFetchingNextPage) {
      fetchNextPage()
    }
  }, [selectedIri, selectedLoaded, hasNextPage, isFetchingNextPage, fetchNextPage])
  useEffect(() => {
    if (selectedLoaded) selectedRef.current?.scrollIntoView({ block: 'nearest' })
  }, [selectedLoaded, selectedIri])

  // Auto-load the next page when a sentinel at the list's end scrolls into view,
  // so large individual sets fill in on scroll instead of requiring repeated
  // clicks. The "Load more" button stays as a keyboard/fallback affordance.
  const sentinelRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    const el = sentinelRef.current
    if (!el || !hasNextPage) return
    const obs = new IntersectionObserver(
      entries => {
        if (entries[0]?.isIntersecting && hasNextPage && !isFetchingNextPage) {
          fetchNextPage()
        }
      },
      { rootMargin: '200px' },
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [hasNextPage, isFetchingNextPage, fetchNextPage])

  if (isLoading) return (
    <div style={{ padding: '6px 12px', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>Loading…</div>
  )
  if (terms.length === 0) return (
    <div style={{ padding: '6px 12px', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>No individuals found</div>
  )

  return (
    <div>
      <ul style={{ listStyle: 'none' }}>
        {terms.map(t => {
          const label = t.label ?? t.iri.split(/[#/]/).pop() ?? t.iri
          const isSelected = selectedIri === t.iri
          return (
            <li key={t.iri}>
              <div
                ref={isSelected ? selectedRef : undefined}
                onClick={() => onSelect(t.iri)}
                style={{
                  padding: '4px 8px 4px 20px',
                  cursor: 'pointer',
                  background: isSelected ? 'var(--bg-hover)' : 'transparent',
                  borderRadius: 'var(--radius-sm)',
                  color: isSelected ? 'var(--accent)' : 'var(--text)',
                  fontSize: 'var(--font-size-sm)',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}
                onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = 'var(--overlay)' }}
                onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = '' }}
                title={t.iri}
              >
                {label}
              </div>
            </li>
          )
        })}
      </ul>
      {hasNextPage && (
        <>
          <button
            onClick={() => fetchNextPage()}
            disabled={isFetchingNextPage}
            style={{
              display: 'block', width: '100%', padding: '6px',
              background: 'none', border: 'none', cursor: 'pointer',
              color: 'var(--text-dim)', fontSize: 11, textAlign: 'center',
            }}
            onMouseEnter={e => (e.currentTarget.style.color = 'var(--accent)')}
            onMouseLeave={e => (e.currentTarget.style.color = 'var(--text-dim)')}
          >
            {isFetchingNextPage ? 'Loading…' : `Load more (${terms.length} loaded)`}
          </button>
          <div ref={sentinelRef} aria-hidden style={{ height: 1 }} />
        </>
      )}
    </div>
  )
}

const PANE_MIN = 220
const PANE_MAX = 640
const PANE_DEFAULT = 300

// ── Mobile detection ──────────────────────────────────────────────────────────

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
  'http://purl.org/vocab/vann/preferredNamespacePrefix',
  'http://purl.org/vocab/vann/preferredNamespaceUri',
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

// Return a safe href for a value that is (entirely) a web/email URL, else null.
// Only http(s) and mailto — never javascript:/data:/etc. Requires the whole
// trimmed value to be a single URL token (no whitespace), so prose that merely
// mentions a URL is left as plain text rather than partially linkified.
export function linkHref(value: string): string | null {
  const v = value.trim()
  if (/^https?:\/\/\S+$/i.test(v)) return v
  if (/^mailto:\S+$/i.test(v)) return v
  return null
}

// Inline external link for a bare URL/mailto value (truncated display).
function ExternalValueLink({ value }: { value: string }) {
  const href = linkHref(value)!
  const display = value.length > 80 ? value.slice(0, 77) + '…' : value
  return (
    <a href={href} target="_blank" rel="noopener noreferrer"
      style={{ color: 'var(--accent)', wordBreak: 'break-all' }}>
      {display} ↗
    </a>
  )
}

function MetaValue({ entry }: { entry: OntologyMetadataEntry }) {
  // Hyperlink any value (IRI- or literal-typed) that is a bare http(s)/mailto
  // URL — e.g. license, homepage, seeAlso, citation stored as plain literals.
  if (linkHref(entry.value)) {
    return (
      <span style={{ wordBreak: 'break-all' }}>
        <ExternalValueLink value={entry.value} />
        {entry.type === 'literal' && entry.language && (
          <span style={{ marginLeft: 4, fontSize: 10, color: 'var(--text-dim)', fontStyle: 'italic' }}>
            @{entry.language}
          </span>
        )}
      </span>
    )
  }
  if (entry.type === 'iri') {
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

function filterByLang(values: OntologyMetadataEntry[], lang: string | null): OntologyMetadataEntry[] {
  if (!lang) return values
  const iris = values.filter(v => v.type === 'iri')
  const literals = values.filter(v => v.type === 'literal')
  const preferred = literals.filter(v => v.language === lang)
  if (preferred.length > 0) return [...iris, ...preferred]
  const untagged = literals.filter(v => !v.language)
  return [...iris, ...(untagged.length > 0 ? untagged : literals)]
}

function OntologyDocMeta({ ontologyId, versionId, lang }: { ontologyId: string; versionId: string; lang?: string | null }) {
  const { data, isLoading } = useQuery({
    queryKey: ['onto-doc-meta', ontologyId, versionId],
    queryFn: () => api.ontologies.ontologyMetadata(ontologyId, versionId),
    staleTime: 300_000,
  })

  // The meta profile decides which header predicates are "relevant": show only
  // those mapped to a role, hiding ones the user unmapped ('-'). Until the
  // profile loads (or if absent), fall back to showing everything so we never
  // flash an empty table. Subscribing here also means a Save on the profile tab
  // (which updates the ['meta-profile'] cache) re-filters this table live.
  const { data: metaProfile } = useOntologyMeta(ontologyId, versionId)
  const mapped: Set<string> | null = metaProfile
    ? new Set(
        Object.entries(metaProfile)
          .filter(([k]) => k.endsWith('_props'))
          .flatMap(([, v]) => (Array.isArray(v) ? (v as string[]) : [])),
      )
    : null

  const predicates = data?.predicates ?? {}
  const entries = Object.entries(predicates)
    .filter(([p]) => !SKIP_PREDICATES.has(p))
    .filter(([p]) => mapped === null || mapped.has(p))
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
              {filterByLang(values, lang ?? null).map((v, i) => (
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

// ── Profile banner ────────────────────────────────────────────────────────────

// ── Metadata + stats panel ────────────────────────────────────────────────────

function OntologyMeta({ iri, version, lang, ownerDisplayName, ownerOrcid }: {
  iri: string
  version: OntologyVersion | undefined
  lang?: string | null
  ownerDisplayName?: string | null
  ownerOrcid?: string | null
}) {
  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['version-stats', version?.ontology_id, version?.id],
    queryFn: () => api.ontologies.stats(version!.ontology_id, version!.id),
    enabled: !!version,
    staleTime: 120_000,
  })
  const langs = useOntologyLanguages(version?.ontology_id, version?.id)

  if (!version) {
    return <div style={{ padding: '2rem', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>Loading…</div>
  }

  const statusColor = version.status === 'ingested' ? 'var(--green)' : 'var(--text-dim)'

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
          {langs.length > 0 && (
            <StatCard label="Languages" value={langs.length} />
          )}
        </div>
      ) : null}

      {/* ── Document metadata ── */}
      <div style={{ marginBottom: 28 }}>
        <OntologyDocMeta ontologyId={version.ontology_id} versionId={version.id} lang={lang} />
      </div>

      {/* ── Repository metadata ── */}
      <h3 style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12 }}>
        Repository Metadata
      </h3>
      <table style={{ borderCollapse: 'collapse', width: '100%', marginBottom: 28 }}>
        <tbody>
          <MetaRow label="Ontology IRI">{linkHref(iri) ? <ExternalValueLink value={iri} /> : iri}</MetaRow>
          {version.version_iri && (
            <MetaRow label="Version IRI">
              {linkHref(version.version_iri) ? <ExternalValueLink value={version.version_iri} /> : version.version_iri}
            </MetaRow>
          )}
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
          {version.reasoner && (
            <MetaRow label="Reasoner">
              <span style={{
                fontSize: 11,
                background: 'var(--bg-secondary)',
                color: 'var(--text-muted)', borderRadius: 3, padding: '1px 7px',
              }}>
                {version.reasoner}
              </span>
            </MetaRow>
          )}
          <MetaRow label="Ingested">{new Date(version.created_at).toLocaleString()}</MetaRow>
          {ownerDisplayName && (
            <MetaRow label="Added by">
              {ownerOrcid ? (
                <a href={`https://orcid.org/${ownerOrcid}`} target="_blank" rel="noreferrer"
                   style={{ color: 'var(--accent)', textDecoration: 'none' }}>
                  {ownerDisplayName} ↗
                </a>
              ) : ownerDisplayName}
            </MetaRow>
          )}
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

function CollapsibleSection({ label, defaultOpen = true, children, headerExtra, openSignal }: {
  label: string; defaultOpen?: boolean; children: React.ReactNode; headerExtra?: React.ReactNode
  // When this changes to a truthy value, force the section open (e.g. a search
  // result selected an entity that lives in this section). The user can still
  // collapse it afterwards; a new signal value re-opens it.
  openSignal?: string | null
}) {
  const [open, setOpen] = useState(defaultOpen)
  useEffect(() => { if (openSignal) setOpen(true) }, [openSignal])
  return (
    <div style={{ borderBottom: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', alignItems: 'center' }}>
        <button
          onClick={() => setOpen(v => !v)}
          style={{
            flex: 1, textAlign: 'left',
            padding: '7px 10px', display: 'flex', alignItems: 'center', gap: 6,
            background: 'none', border: 'none', cursor: 'pointer',
            color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 1,
          }}
        >
          <span style={{ fontSize: 9, flexShrink: 0 }}>{open ? '▾' : '▸'}</span>
          {label}
        </button>
        {headerExtra && <div style={{ paddingRight: 10, flexShrink: 0 }}>{headerExtra}</div>}
      </div>
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
  ontologyId, versionId, onSelect, lang,
}: { ontologyId: string; versionId: string; onSelect: (iri: string) => void; lang?: string | null }) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [activeIdx, setActiveIdx] = useState(-1)
  const dq = useDebounce(query, 200)
  const containerRef = useRef<HTMLDivElement>(null)

  const { data } = useQuery({
    queryKey: ['onto-search', ontologyId, versionId, dq, lang],
    queryFn: () => api.ontologies.search(ontologyId, versionId, dq, 'auto', lang ?? undefined, dq.length >= 3),
    enabled: dq.length >= 2,
    staleTime: 30_000,
  })

  const results: SearchResult[] = data?.results ?? []
  const semanticResults: SearchResult[] = data?.semantic_results ?? []

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

  const totalItems = results.length + semanticResults.length

  function handleKey(e: React.KeyboardEvent) {
    if (!open || totalItems === 0) return
    if (e.key === 'ArrowDown') { e.preventDefault(); setActiveIdx(i => Math.min(i + 1, totalItems - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActiveIdx(i => Math.max(i - 1, 0)) }
    else if (e.key === 'Enter' && activeIdx >= 0) {
      e.preventDefault()
      if (activeIdx < results.length) pick(results[activeIdx])
      else pick(semanticResults[activeIdx - results.length])
    }
    else if (e.key === 'Escape') { setOpen(false) }
  }

  return (
    <div ref={containerRef} style={{ position: 'relative', padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>
      <input
        value={query}
        onChange={e => { setQuery(e.target.value); setOpen(true) }}
        onFocus={() => { if (query) setOpen(true) }}
        onKeyDown={handleKey}
        placeholder="Search classes, properties & individuals…"
        style={{
          width: '100%', boxSizing: 'border-box',
          padding: '5px 8px', fontSize: 'var(--font-size-sm)',
          background: 'var(--bg)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)', color: 'var(--text)',
          outline: 'none',
        }}
      />
      {open && (results.length > 0 || semanticResults.length > 0) && (
        <ul style={{
          position: 'absolute', top: '100%', left: 8, right: 8,
          zIndex: 100, listStyle: 'none', margin: 0, padding: 0,
          background: 'var(--bg-secondary)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius-sm)', boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
          maxHeight: 320, overflowY: 'auto',
        }}>
          {results.map((r, i) => {
            const isInd = r.type === 'individual'
            const isProp = r.type?.endsWith('_property')
            const typeColor = isInd ? 'var(--accent-blue)' : isProp ? 'var(--accent-purple)' : 'var(--text-dim)'
            return (
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
                  borderRadius: 3, background: 'var(--bg)', color: typeColor,
                  flexShrink: 0,
                }}>
                  {isInd ? 'ind' : r.short}
                </span>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {r.label}
                </span>
              </li>
            )
          })}
          {semanticResults.length > 0 && (
            <>
              <li style={{
                fontSize: 10, color: 'var(--text-dim)', padding: '4px 10px 2px',
                textTransform: 'uppercase', letterSpacing: 0.6,
                borderTop: '1px solid var(--border)',
              }}>
                Semantically similar
              </li>
              {semanticResults.map((r, i) => {
                const alreadyShown = results.some(p => p.iri === r.iri)
                const isInd = r.type === 'individual'
                const isProp = r.type?.endsWith('_property')
                const typeColor = isInd
                  ? 'var(--accent-blue)'
                  : isProp ? 'var(--accent-purple)' : 'var(--text-dim)'
                return (
                  <li
                    key={r.iri}
                    onMouseDown={() => pick(r)}
                    onMouseEnter={() => setActiveIdx(results.length + i)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 6,
                      padding: '5px 10px', cursor: 'pointer', fontSize: 'var(--font-size-sm)',
                      background: activeIdx === results.length + i ? 'var(--bg-hover)' : 'transparent',
                      color: alreadyShown ? 'var(--text-dim)' : 'var(--text)',
                      opacity: alreadyShown ? 0.6 : 1,
                    }}
                  >
                    <span style={{
                      fontSize: 9, fontWeight: 700, padding: '1px 4px',
                      borderRadius: 2, background: 'var(--bg)',
                      color: typeColor, flexShrink: 0, minWidth: 28, textAlign: 'center',
                    }}>
                      {r.type === 'class' ? 'cls' : r.type === 'individual' ? 'ind' : 'prop'}
                    </span>
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {r.label}
                    </span>
                    <span style={{ fontSize: 10, color: 'var(--text-dim)', flexShrink: 0 }}>
                      {r.score?.toFixed(2)}
                    </span>
                  </li>
                )
              })}
            </>
          )}
        </ul>
      )}
    </div>
  )
}

function MOSQueryPane({
  ontologyId, versionId, onSelect, lang,
}: {
  ontologyId: string
  versionId: string
  onSelect: (iri: string) => void
  lang?: string | null
}) {
  const [mosQuery, setMosQuery] = useState('')

  const { data, error, isFetching } = useQuery({
    queryKey: ['onto-mos', ontologyId, versionId, mosQuery, lang],
    queryFn: () => api.ontologies.search(ontologyId, versionId, mosQuery, 'expression', lang ?? undefined),
    enabled: mosQuery.length >= 2,
    staleTime: 10_000,
    retry: false,
  })

  const results = data?.results ?? []
  const errBody = (error as (Error & { body?: { error?: string; detail?: string } }) | null)?.body
  const errMsg = !error ? null
    : errBody?.error === 'not_classified' ? 'Reasoning not ready — try again in a few minutes.'
    : errBody?.error === 'ambiguous_label' ? 'Ambiguous label — use a CURIE or be more specific.'
    : errBody?.error === 'unresolved_term' ? (errBody.detail ?? 'Term not found in this ontology.')
    : (errBody?.detail ?? errBody?.error ?? (error as Error).message)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
      <div style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
        <SearchBar
          ontologyId={ontologyId}
          versionId={versionId}
          onSearch={setMosQuery}
          placeholder="cell, 'cell death', GO:0008150"
        />
        <p style={{ color: 'var(--text-dim)', fontSize: 10, margin: '4px 2px 0', lineHeight: 1.4 }}>
          Use <code>and</code>, <code>or</code>, <code>some</code>, <code>only</code>, <code>not</code>
          {' · '}quote multi-word names: <code>'cell death'</code>
        </p>
      </div>
      <div style={{ flex: 1, overflow: 'auto' }}>
        {!mosQuery && (
          <p style={{ padding: '8px 12px', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
            Type a MOS expression and press Enter.
          </p>
        )}
        {isFetching && (
          <p style={{ padding: '8px 12px', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>Searching…</p>
        )}
        {!isFetching && errMsg && (
          <p style={{ padding: '8px 12px', color: 'var(--error)', fontSize: 'var(--font-size-sm)', lineHeight: 1.5 }}>
            {errMsg}
          </p>
        )}
        {!isFetching && !error && mosQuery.length >= 2 && results.length === 0 && (
          <p style={{ padding: '8px 12px', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
            No results for "{mosQuery}"
          </p>
        )}
        {results.length > 0 && (
          <div style={{ padding: '4px 10px', fontSize: 10, color: 'var(--text-dim)', borderBottom: '1px solid var(--border)' }}>
            {results.length}{data?.truncated ? '+' : ''} result{results.length !== 1 ? 's' : ''}
          </div>
        )}
        <ul style={{ listStyle: 'none' }}>
          {results.map(r => {
            const isProp = r.type?.endsWith('_property')
            const isInd  = r.type === 'individual'
            const typeColor = isInd ? 'var(--accent-blue)' : isProp ? 'var(--accent-purple)' : 'var(--text-dim)'
            return (
              <li key={r.iri}>
                <div
                  role="button"
                  onClick={() => onSelect(r.iri)}
                  style={{
                    padding: '5px 10px', cursor: 'pointer',
                    display: 'flex', alignItems: 'center', gap: 6,
                    borderBottom: '1px solid var(--border)',
                    fontSize: 'var(--font-size-sm)',
                  }}
                  onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-hover)' }}
                  onMouseLeave={e => { e.currentTarget.style.background = '' }}
                >
                  <span style={{
                    fontSize: 9, fontWeight: 700, padding: '1px 4px', borderRadius: 3,
                    background: 'var(--bg)', color: typeColor, flexShrink: 0,
                  }}>
                    {isInd ? 'ind' : r.short}
                  </span>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {r.label}
                  </span>
                </div>
              </li>
            )
          })}
        </ul>
      </div>
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

  const ontology = ontologies.find(o => slugFromIri(o.iri) === slug || o.shortname === slug)
  const { data: versionsData, isLoading: versionsLoading } = useVersions(ontology?.id)
  const versions = versionsData?.versions ?? []

  const activeVersion = version
    ? versions.find(v => v.id === version) ?? versions[0]
    : versions[0]
  const activeVid = activeVersion?.id

  // Fire a one-per-session view beacon once the ontology resolves.
  useEffect(() => {
    const id = ontology?.id
    if (!id || _viewedBeacons.has(id)) return
    _viewedBeacons.add(id)
    api.ontologies.recordView(id).catch(() => {})
  }, [ontology?.id])
  const oid = ontology?.id

  const selectedTermIri = searchParams.get('term')
  const { data: versionStats } = useQuery({
    queryKey: ['version-stats', oid, activeVid],
    queryFn: () => api.ontologies.stats(oid!, activeVid!),
    enabled: !!oid && !!activeVid,
    staleTime: 120_000,
  })
  const individualCount = versionStats?.individual_count ?? 0

  const [classMode, setClassMode] = useState<HierarchyMode>('asserted')
  const [mobilePane, setMobilePane] = useState<'tree' | 'detail'>('tree')
  const [detailTab, setDetailTab] = useState<'info' | 'profile' | 'history' | 'coverage' | 'owl-profile' | 'reuse'>('info')
  const location = useLocation()
  useEffect(() => {
    if (location.hash === '#owl-profile') {
      setDetailTab('owl-profile')
    } else if (location.hash === '#coverage') {
      setDetailTab('coverage')
    } else if (location.hash === '#reuse') {
      setDetailTab('reuse')
    }
  }, [location.hash])
  const [leftTab, setLeftTab] = useState<'browse' | 'query'>('browse')

  const [hideInverseProps, setHideInverseProps] = useState(true)
  const [hideObsolete, setHideObsolete] = useState(true)
  const [classExpand,   setClassExpand]   = useState(0)
  const [classCollapse, setClassCollapse] = useState(0)
  const [objExpand,     setObjExpand]     = useState(0)
  const [objCollapse,   setObjCollapse]   = useState(0)
  const [dataExpand,    setDataExpand]    = useState(0)
  const [dataCollapse,  setDataCollapse]  = useState(0)

  const { effectiveLang } = useLang()
  const ontologyLangs = useOntologyLanguages(oid, activeVid)

  // Auto-reveal inverses when navigating to a term that is itself an inverse target
  const { data: selectedTermData } = useTerm(oid ?? null, activeVid ?? null, selectedTermIri, effectiveLang)
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
        {/* The same picker as the navigation bar, over this ontology's own
            languages rather than the whole repository's. Both write the same
            session language, so the two stay in step; offering a language this
            ontology has no labels in would just be a choice that does nothing. */}
        {ontologyLangs.length > 0 && (
          <LanguagePicker
            languages={ontologyLangs}
            align="right"
            title="Display language for labels — applies to everything you view, and only to you"
          />
        )}
      </div>

      {/* Left pane tabs: Browse | Query */}
      <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
        {(['browse', 'query'] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setLeftTab(tab)}
            style={{
              flex: 1, padding: '6px 0', border: 'none', cursor: 'pointer',
              fontSize: 11, fontWeight: 500,
              background: leftTab === tab ? 'var(--bg)' : 'transparent',
              color: leftTab === tab ? 'var(--text)' : 'var(--text-dim)',
              borderBottom: leftTab === tab ? '2px solid var(--accent)' : '2px solid transparent',
            }}
          >
            {tab === 'browse' ? 'Browse' : 'Query'}
          </button>
        ))}
      </div>

      {leftTab === 'browse' ? (<>

      {/* Search bar */}
      {oid && activeVid && (
        <OntologySearchBar ontologyId={oid} versionId={activeVid} onSelect={selectTerm} lang={effectiveLang} />
      )}

      {/* Hierarchy controls */}
      <div style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
        <button
          onClick={() => setHideObsolete(v => !v)}
          title={hideObsolete ? 'Show obsolete terms' : 'Hide obsolete terms'}
          style={{
            fontSize: 9, padding: '2px 6px', borderRadius: 3,
            border: '1px solid var(--border)', background: 'none',
            color: hideObsolete ? 'var(--text-dim)' : 'var(--accent)',
            cursor: 'pointer', textTransform: 'uppercase', letterSpacing: 0.5,
          }}
          onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--text-muted)' }}
          onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)' }}
        >
          {hideObsolete ? 'Show Obsolete' : 'Hide Obsolete'}
        </button>
      </div>

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
                      padding: '2px 6px', fontSize: 10, border: 'none', cursor: 'pointer',
                      background: classMode === m ? 'var(--accent)' : 'transparent',
                      color: classMode === m ? 'var(--on-accent)' : 'var(--text-dim)',
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
              hideObsolete={hideObsolete}
              expandSignal={classExpand} collapseSignal={classCollapse}
              lang={effectiveLang}
            />
          </div>
          <CollapsibleSection label="Object Properties" defaultOpen={true} headerExtra={<ExpandToggleBtn
              onExpand={() => setObjExpand(v => v + 1)}
              onCollapse={() => setObjCollapse(v => v + 1)}
            />}>
            <div style={{ padding: '4px 10px 2px' }}>
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
                {hideInverseProps ? 'Show Inverses' : 'Hide Inverses'}
              </button>
            </div>
            <ClassTree
              ontologyId={oid} versionId={activeVid}
              selectedIri={selectedTermIri} onSelect={selectTerm}
              entityType="object_property" revealIri={selectedTermIri}
              hideInverse={hideInverseProps} hideObsolete={hideObsolete}
              expandSignal={objExpand} collapseSignal={objCollapse}
              lang={effectiveLang}
            />
          </CollapsibleSection>
          <CollapsibleSection label="Data Properties" defaultOpen={true} headerExtra={<ExpandToggleBtn
              onExpand={() => setDataExpand(v => v + 1)}
              onCollapse={() => setDataCollapse(v => v + 1)}
            />}>
            <ClassTree
              ontologyId={oid} versionId={activeVid}
              selectedIri={selectedTermIri} onSelect={selectTerm}
              entityType="data_property" revealIri={selectedTermIri}
              hideObsolete={hideObsolete}
              expandSignal={dataExpand} collapseSignal={dataCollapse}
              lang={effectiveLang}
            />
          </CollapsibleSection>
          <CollapsibleSection label="Annotation Properties" defaultOpen={false}>
            <ClassTree
              ontologyId={oid} versionId={activeVid}
              selectedIri={selectedTermIri} onSelect={selectTerm}
              entityType="annotation_property" revealIri={selectedTermIri}
              hideObsolete={hideObsolete}
              lang={effectiveLang}
            />
          </CollapsibleSection>
          {individualCount > 0 && (
            <CollapsibleSection
              label={`Individuals (${individualCount.toLocaleString()})`}
              defaultOpen={false}
              openSignal={selectedTermData?.entityType === 'individual' ? selectedTermIri : null}
            >
              <IndividualList
                ontologyId={oid} versionId={activeVid}
                selectedIri={selectedTermIri} onSelect={selectTerm}
                lang={effectiveLang}
              />
            </CollapsibleSection>
          )}
          <CollapsibleSection label="Incremental reasoning" defaultOpen={false}>
            <IncrementalReasoningPanel ontologyId={oid} versionId={activeVid} />
          </CollapsibleSection>
        </div>
      ) : (
        <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
          {versionsLoading ? 'Loading…' : 'No versions available'}
        </div>
      )}
      </>) : (
        oid && activeVid
          ? <MOSQueryPane
              ontologyId={oid}
              versionId={activeVid}
              onSelect={iri => { selectTerm(iri); setLeftTab('browse') }}
              lang={effectiveLang}
            />
          : null
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
          lang={effectiveLang}
          versionReasoner={activeVersion?.reasoner}
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
          {/* Tab bar */}
          <div style={{
            display: 'flex', borderBottom: '1px solid var(--border)',
            background: 'var(--bg-secondary)', flexShrink: 0,
          }}>
            {(['info', 'profile', 'history', 'coverage', 'owl-profile', 'reuse'] as const).map(tab => (
              <button
                key={tab}
                onClick={() => setDetailTab(tab)}
                style={{
                  padding: '8px 16px', border: 'none', cursor: 'pointer', fontSize: 12,
                  background: detailTab === tab ? 'var(--bg)' : 'transparent',
                  color: detailTab === tab ? 'var(--text)' : 'var(--text-dim)',
                  borderBottom: detailTab === tab ? '2px solid var(--accent)' : '2px solid transparent',
                  textTransform: 'capitalize',
                  whiteSpace: 'nowrap',
                }}
              >
                {tab === 'owl-profile' ? 'OWL Profile' : tab === 'reuse' ? 'Reuse' : tab}
              </button>
            ))}
          </div>
          {/* Tab content */}
          <div style={{ flex: 1, overflow: 'auto' }}>
            {detailTab === 'info' ? (
              <OntologyMeta
                iri={ontology?.iri ?? ''}
                version={activeVersion}
                lang={effectiveLang}
                ownerDisplayName={ontology?.owner_display_name}
                ownerOrcid={ontology?.owner_orcid}
              />
            ) : detailTab === 'history' ? (
              oid && activeVid && versions.length > 1
                ? <HistoryTab
                    ontologyId={oid}
                    shortname={ontology?.shortname ?? slug ?? ''}
                    currentVersionId={activeVid}
                    versions={versions}
                  />
                : <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 12 }}>
                    Only one version available — no diff to show.
                  </div>
            ) : detailTab === 'coverage' ? (
              oid && activeVid
                ? <CoverageSection ontologyId={oid} versionId={activeVid} />
                : <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 12 }}>
                    No version available.
                  </div>
            ) : detailTab === 'owl-profile' ? (
              oid && activeVid
                ? <OwlProfileSection ontologyId={oid} versionId={activeVid} />
                : <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 12 }}>
                    No version available.
                  </div>
            ) : detailTab === 'reuse' ? (
              oid && activeVid
                ? <ReuseSection ontologyId={oid} versionId={activeVid} />
                : <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 12 }}>
                    No version available.
                  </div>
            ) : (
              oid && activeVid
                ? <>
                    <div style={{
                      padding: '8px 16px 4px', fontSize: 10, fontWeight: 600,
                      color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 0.8,
                    }}>
                      Ontology Metadata
                    </div>
                    <MetaProfileEditor ontologyId={oid} versionId={activeVid} />
                    <div style={{
                      padding: '8px 16px 4px', fontSize: 10, fontWeight: 600,
                      color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: 0.8,
                      borderTop: '1px solid var(--border)',
                    }}>
                      Term Profile
                    </div>
                    <ProfileEditor ontologyId={oid} versionId={activeVid} />
                  </>
                : null
            )}
          </div>
        </div>
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
