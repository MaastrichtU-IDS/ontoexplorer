import { useState, useMemo, memo, useRef, useEffect, lazy, Suspense } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useWindowVirtualizer } from '@tanstack/react-virtual'
import { useOntologiesInfinite } from '../hooks/useOntologiesInfinite'
import { useRepositoryLanguages } from '../hooks/useRepositoryLanguages'
import { useIsMobile } from '../hooks/useIsMobile'
import { api, Ontology, OwlProfileFleetEntry, ProfileName, LanguageTier, slugFromIri } from '../lib/api'
import { endonym } from '../components/LanguagePicker'

// The secondary tabs (Coverage/OWL Profile/Compare/Reuse — the last two pull the
// heavier diff/compare code) only render when their tab is active, so lazy-load
// them: the default List tab, the /ontologies landing view, ships without them.
const Coverage = lazy(() => import('./Coverage'))
const OwlProfile = lazy(() => import('./OwlProfile'))
const Compare = lazy(() => import('./Compare'))
const Reuse = lazy(() => import('./Reuse').then(m => ({ default: m.Reuse })))

type Tab = 'list' | 'coverage' | 'profiles' | 'compare' | 'reuse'
const TAB_VALUES: Tab[] = ['list', 'coverage', 'profiles', 'compare', 'reuse']
const TAB_LABELS: Record<Tab, string> = {
  list:        'List',
  coverage:    'Coverage',
  profiles:    'OWL Profile',
  compare:     'Compare',
  reuse:       'Reuse',
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtCount(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`
  return String(n)
}

function displayName(o: Ontology): string {
  if (o.shortname) return o.shortname
  const last = o.iri.replace(/[/#]+$/, '').split(/[/#]/).pop() ?? o.iri
  return last.replace(/\.(owl|ttl|rdf|obo|json|xml|nt)$/i, '')
}

const GROUP_LABELS: Record<string, string> = {
  upper:       'Upper Ontology',
  sulo_family: 'SULO Family',
  metadata:    'Metadata',
  obo:         'OBO Foundry',
  biomedical:  'Biomedical',
  bioportal:   'BioPortal',
  lov:         'LOV',
}

const GROUP_COLORS: Record<string, { bg: string; border: string; color: string }> = {
  upper:       { bg: 'rgba(97,175,239,0.12)',  border: 'rgba(97,175,239,0.4)',  color: 'var(--od-blue)' },
  sulo_family: { bg: 'rgba(229,192,123,0.12)', border: 'rgba(229,192,123,0.4)', color: 'var(--od-yellow)' },
  metadata:    { bg: 'rgba(198,120,221,0.12)', border: 'rgba(198,120,221,0.4)', color: 'var(--od-purple)' },
  obo:         { bg: 'rgba(152,195,121,0.12)', border: 'rgba(152,195,121,0.4)', color: 'var(--od-green)' },
  biomedical:  { bg: 'rgba(224,108,117,0.12)', border: 'rgba(224,108,117,0.4)', color: 'var(--error)' },
  bioportal:   { bg: 'rgba(86,182,194,0.12)',  border: 'rgba(86,182,194,0.4)',  color: 'var(--od-cyan)' },
  lov:         { bg: 'rgba(240,136,62,0.12)',  border: 'rgba(240,136,62,0.4)',  color: 'var(--orange)' },
}

function IriChip({ iri }: { iri: string }) {
  const [copied, setCopied] = useState(false)
  function copy(e: React.MouseEvent) {
    e.preventDefault()
    e.stopPropagation()
    navigator.clipboard.writeText(iri).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }
  return (
    <button
      onClick={copy}
      title={iri}
      style={{
        fontSize: 10, padding: '1px 7px', borderRadius: 3,
        border: '1px solid var(--border)',
        background: copied ? 'rgba(100,200,100,0.1)' : 'transparent',
        color: copied ? 'var(--accent)' : 'var(--text-dim)',
        cursor: 'pointer', fontFamily: 'monospace', flexShrink: 0,
      }}
    >
      {copied ? '✓ copied' : 'IRI'}
    </button>
  )
}

// ── Row ───────────────────────────────────────────────────────────────────────

const PROFILE_BADGE_COLORS: Record<ProfileName, { bg: string; border: string; color: string }> = {
  el: { bg: 'rgba(97,175,239,0.12)',  border: 'rgba(97,175,239,0.4)',  color: 'var(--od-blue)' },
  rl: { bg: 'rgba(152,195,121,0.12)', border: 'rgba(152,195,121,0.4)', color: 'var(--od-green)' },
  ql: { bg: 'rgba(229,192,123,0.12)', border: 'rgba(229,192,123,0.4)', color: 'var(--od-yellow)' },
  dl: { bg: 'rgba(198,120,221,0.12)', border: 'rgba(198,120,221,0.4)', color: 'var(--od-purple)' },
}

function ProfileBadges({ entry }: { entry: OwlProfileFleetEntry | undefined }) {
  if (!entry) return null
  const profiles: ProfileName[] = (['dl', 'el', 'ql', 'rl'] as const).filter(p => {
    if (p === 'dl') return entry.in_dl
    if (p === 'el') return entry.in_el
    if (p === 'ql') return entry.in_ql
    return entry.in_rl
  })
  if (profiles.length === 0) return null
  return (
    <>
      {profiles.map(p => {
        const c = PROFILE_BADGE_COLORS[p]
        return (
          <span
            key={p}
            title={`Conforms to OWL 2 ${p.toUpperCase()}`}
            style={{
              fontSize: 9, padding: '1px 6px', borderRadius: 10,
              background: c.bg, border: `1px solid ${c.border}`,
              color: c.color, fontWeight: 600, letterSpacing: 0.3, flexShrink: 0,
            }}
          >
            {p.toUpperCase()}
          </span>
        )
      })}
    </>
  )
}

const OntologyRow = memo(function OntologyRow({ o, profileEntry }: { o: Ontology; profileEntry: OwlProfileFleetEntry | undefined }) {
  const navigate = useNavigate()
  const [descExpanded, setDescExpanded] = useState(false)
  const latest = o.latest_version
  const hasStats = o.class_count != null || o.property_count != null || o.triple_count != null || o.individual_count != null || o.object_property_count != null
  const knownGroups = (o.groups ?? []).filter(g => g in GROUP_LABELS)
  const lastModified = latest?.created_at ?? o.created_at

  return (
    <div
      className="ontology-row"
      onClick={() => latest && navigate(`/ontologies/${o.shortname ?? slugFromIri(o.iri)}`)}
      style={{ cursor: latest ? 'pointer' : 'default', borderBottom: '2px solid var(--border)', padding: '10px 12px' }}
    >
        {/* Name · IRI chip · group badges */}
        {o.label && (
          <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)', marginBottom: 2 }}>
            {o.label}
          </div>
        )}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ color: 'var(--accent)', fontWeight: 500 }}>{displayName(o)}</span>
          <IriChip iri={o.iri} />
          <TierChip tier={o.language_tier} />
          <ProfileBadges entry={profileEntry} />
          {knownGroups.map(g => {
            const c = GROUP_COLORS[g]
            return (
              <span key={g} style={{
                fontSize: 9, padding: '1px 6px', borderRadius: 10,
                background: c.bg, border: `1px solid ${c.border}`,
                color: c.color, fontWeight: 600, letterSpacing: 0.3, flexShrink: 0,
              }}>
                {GROUP_LABELS[g]}
              </span>
            )
          })}
        </div>

        {/* Languages */}
        {(o.languages ?? []).length > 0 && (
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 6 }}>
            {o.languages!.map(l => (
              <span key={l.lang} title={`${l.label_count} labels in ${l.lang}`} style={{
                fontSize: 9, padding: '1px 6px', borderRadius: 10,
                background: 'rgba(86,182,194,0.10)', border: '1px solid rgba(86,182,194,0.35)',
                color: 'var(--od-cyan)', fontWeight: 600, letterSpacing: 0.3, flexShrink: 0,
              }}>
                {l.lang}
              </span>
            ))}
          </div>
        )}

        {/* Description */}
        {o.description && (() => {
          const TRUNC_AT = 280
          const needsToggle = o.description.length > TRUNC_AT
          const shown = !descExpanded && needsToggle
            ? o.description.slice(0, TRUNC_AT).trimEnd() + '… '
            : o.description + (needsToggle ? ' ' : '')
          return (
            <div style={{ marginTop: 6, color: 'var(--text-dim)', fontSize: 11, lineHeight: 1.4 }}>
              {shown}
              {needsToggle && (
                <button
                  onClick={e => { e.stopPropagation(); setDescExpanded(v => !v) }}
                  style={{
                    fontSize: 10, color: 'var(--accent)', background: 'none',
                    border: 'none', padding: 0, cursor: 'pointer',
                  }}
                >
                  {descExpanded ? 'less' : 'more…'}
                </button>
              )}
            </div>
          )
        })()}

        {/* Stats · last modified */}
        <div style={{
          marginTop: 6, color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)',
          fontVariantNumeric: 'tabular-nums',
        }}>
          {hasStats ? (
            <>
              {fmtCount(o.class_count)} cls
              {o.object_property_count != null && o.object_property_count > 0 && (
                <><span style={{ color: 'var(--border)', margin: '0 4px' }}>·</span>{fmtCount(o.object_property_count)} obj</>
              )}
              {o.datatype_property_count != null && o.datatype_property_count > 0 && (
                <><span style={{ color: 'var(--border)', margin: '0 4px' }}>·</span>{fmtCount(o.datatype_property_count)} data</>
              )}
              {o.annotation_property_count != null && o.annotation_property_count > 0 && (
                <><span style={{ color: 'var(--border)', margin: '0 4px' }}>·</span>{fmtCount(o.annotation_property_count)} ann</>
              )}
              {o.individual_count != null && o.individual_count > 0 && (
                <><span style={{ color: 'var(--border)', margin: '0 4px' }}>·</span>{fmtCount(o.individual_count)} ind</>
              )}
              {o.triple_count != null && (
                <><span style={{ color: 'var(--border)', margin: '0 4px' }}>·</span>{fmtCount(o.triple_count)} axioms</>
              )}
              <span style={{ color: 'var(--border)', margin: '0 4px' }}>·</span>
            </>
          ) : null}
          <span title={`Last modified ${new Date(lastModified).toLocaleString()}`}>
            modified {new Date(lastModified).toLocaleDateString()}
          </span>
        </div>
    </div>
  )
})

// ── Sort ─────────────────────────────────────────────────────────────────────

type SortCol = 'name' | 'date'
type SortDir = 'asc' | 'desc'

// ── Group filter ─────────────────────────────────────────────────────────────

const GROUPS: { value: string; label: string }[] = [
  { value: '',            label: 'All' },
  { value: 'upper',       label: 'Upper Ontology' },
  { value: 'sulo_family', label: 'SULO Family' },
  { value: 'metadata',    label: 'Metadata' },
  { value: 'obo',         label: 'OBO Foundry' },
  { value: 'biomedical',  label: 'Biomedical' },
  { value: 'bioportal',   label: 'BioPortal' },
  { value: 'lov',         label: 'LOV' },
]

// ── Profile filter ────────────────────────────────────────────────────────────

// ── Expressivity filter ───────────────────────────────────────────────────────
// One selector combining the language tiers with the OWL 2 profiles. Tiers drive
// the `language` filter; profiles drive the `profile` filter; the two are mutually
// exclusive in the UI (picking one clears the other). Ordered coarsest→finest:
// the OWL 2 profiles sit under OWL (between OWL and RDFS-Plus).
type ExprOption =
  | { kind: 'all'; label: string }
  | { kind: 'tier'; value: LanguageTier; label: string }
  | { kind: 'profile'; value: ProfileName; label: string }

const EXPRESSIVITY_OPTIONS: ExprOption[] = [
  { kind: 'all',                          label: 'All' },
  { kind: 'tier',    value: 'owl',        label: 'OWL' },
  { kind: 'profile', value: 'dl',         label: 'OWL 2 DL' },
  { kind: 'profile', value: 'el',         label: 'OWL 2 EL' },
  { kind: 'profile', value: 'ql',         label: 'OWL 2 QL' },
  { kind: 'profile', value: 'rl',         label: 'OWL 2 RL' },
  { kind: 'tier',    value: 'rdfs-plus',  label: 'RDFS-Plus' },
  { kind: 'tier',    value: 'rdfs',       label: 'RDFS' },
  { kind: 'tier',    value: 'rdf',        label: 'RDF' },
]

const TIER_BADGE: Record<string, { label: string; color: string }> = {
  rdf: { label: 'RDF', color: '#8a8f98' },
  rdfs: { label: 'RDFS', color: '#2f9e6f' },
  'rdfs-plus': { label: 'RDFS-Plus', color: '#3b82c4' },
  owl: { label: 'OWL', color: '#8b5cf6' },
}

function TierChip({ tier }: { tier?: string | null }) {
  if (!tier) return null
  const t = TIER_BADGE[tier]
  if (!t) return null
  return (
    <span
      title={`Language tier: ${t.label}`}
      style={{
        fontSize: 10, fontWeight: 700, padding: '1px 7px', borderRadius: 999,
        color: '#fff', background: t.color, whiteSpace: 'nowrap',
      }}
    >
      {t.label}
    </span>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Ontologies() {
  const [searchParams, setSearchParams] = useSearchParams()
  const tabParam = searchParams.get('tab')
  const tab: Tab = (TAB_VALUES as string[]).includes(tabParam ?? '')
    ? (tabParam as Tab)
    : 'list'
  function setTab(next: Tab) {
    const params = new URLSearchParams(searchParams)
    if (next === 'list') params.delete('tab')
    else params.set('tab', next)
    setSearchParams(params)
  }

  const isMobile = useIsMobile()
  const [query, setQuery] = useState('')
  const [group, setGroup] = useState('')
  const [profile, setProfile] = useState<'' | ProfileName>('')
  const [language, setLanguage] = useState<'' | LanguageTier>('')
  const [langs, setLangs] = useState<Set<string>>(new Set())
  const [langsExpanded, setLangsExpanded] = useState(false)
  const [sortCol, setSortCol] = useState<SortCol>('name')
  const [sortDir, setSortDir] = useState<SortDir>('asc')
  const reuses = searchParams.get('reuses') ?? undefined
  // Server-side pagination: the server owns sort + every filter (incl. the
  // language-code facet), and we page in on scroll. `ontologies` is the pages
  // flattened; `total` is the full match count for the header.
  const {
    ontologies, total, isLoading,
    fetchNextPage, hasNextPage, isFetchingNextPage,
  } = useOntologiesInfinite({
    query,
    group: group || undefined,
    profile: profile || undefined,
    reuses,
    language: language || undefined,
    langs: [...langs],
    sort: sortCol,
    dir: sortDir,
  })
  const repoLangs = useRepositoryLanguages()
  const { data: profileFleet } = useQuery({
    queryKey: ['owl-profile', 'fleet'],
    queryFn: () => api.owl_profile.fleet(),
    staleTime: 60_000,
  })
  const profileByOntologyId = useMemo(() => {
    const m = new Map<string, OwlProfileFleetEntry>()
    for (const e of profileFleet?.ontologies ?? []) m.set(e.id, e)
    return m
  }, [profileFleet])

  function toggleLang(lang: string) {
    setLangs(prev => {
      const next = new Set(prev)
      next.has(lang) ? next.delete(lang) : next.add(lang)
      return next
    })
  }

  function handleSort(col: SortCol) {
    if (col === sortCol) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(col); setSortDir('asc') }
  }

  // Virtualize the list: rows are non-trivial and the catalog is large, so
  // window-scroll virtualization renders only the visible window while keeping
  // the full-page scroll UX. Rows are variable-height (optional label/languages/
  // description/stats + expand toggle), measured dynamically via measureElement.
  const listRef = useRef<HTMLDivElement>(null)
  const rowVirtualizer = useWindowVirtualizer({
    count: ontologies.length,
    estimateSize: () => 96,
    overscan: 8,
    getItemKey: (i) => ontologies[i].id,
    scrollMargin: listRef.current?.offsetTop ?? 0,
  })

  // Infinite scroll: fetch the next page once the virtualizer is rendering
  // within a few rows of the end of what's loaded.
  const virtualItems = rowVirtualizer.getVirtualItems()
  const lastVisibleIndex = virtualItems.length ? virtualItems[virtualItems.length - 1].index : 0
  useEffect(() => {
    if (lastVisibleIndex >= ontologies.length - 8 && hasNextPage && !isFetchingNextPage) {
      fetchNextPage()
    }
  }, [lastVisibleIndex, ontologies.length, hasNextPage, isFetchingNextPage, fetchNextPage])

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: isMobile ? '0.75rem 0.75rem' : '2rem 1.5rem' }}>
      <h1 style={{ color: 'var(--text)', fontSize: 20, fontWeight: 700, marginBottom: '1rem' }}>
        Ontologies
      </h1>

      {/* Tab strip */}
      <div style={{
        display: 'flex', gap: 0, borderBottom: '1px solid var(--border)',
        marginBottom: '1.25rem',
        flexWrap: 'wrap',
      }}>
        {TAB_VALUES.map(t => {
          const active = tab === t
          return (
            <button
              key={t}
              onClick={() => setTab(t)}
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                padding: '8px 14px', fontSize: 13,
                color: active ? 'var(--text)' : 'var(--text-dim)',
                fontWeight: active ? 600 : 400,
                borderBottom: '2px solid',
                borderBottomColor: active ? 'var(--accent)' : 'transparent',
                marginBottom: -1,
                flexShrink: 0, whiteSpace: 'nowrap',
              }}
            >
              {TAB_LABELS[t]}
            </button>
          )
        })}
      </div>

      {tab !== 'list' && (
        <Suspense fallback={<p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>Loading…</p>}>
          {tab === 'coverage' && <Coverage />}
          {tab === 'profiles' && <OwlProfile />}
          {tab === 'compare' && <Compare />}
          {tab === 'reuse' && <Reuse />}
        </Suspense>
      )}
      {tab === 'list' && <>
      {/* Group filter chips */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginBottom: '0.6rem' }}>
        <span style={{ fontSize: 11, color: 'var(--text-dim)', marginRight: 2 }}>Group:</span>
        {GROUPS.map(g => {
          const active = group === g.value
          const c = g.value ? GROUP_COLORS[g.value] : null
          return (
            <button
              key={g.value}
              onClick={() => setGroup(g.value)}
              style={{
                fontSize: 12, padding: '4px 12px', borderRadius: 20,
                border: '1px solid',
                borderColor: active && c ? c.border : active ? 'var(--accent)' : 'var(--border)',
                cursor: 'pointer',
                background: active
                  ? (c ? c.bg : 'var(--accent)')
                  : (c ? c.bg : 'var(--bg-secondary)'),
                color: c ? c.color : (active ? 'var(--on-accent)' : 'var(--text-dim)'),
                fontWeight: active ? 700 : 500,
                opacity: active || !c ? 1 : 0.65,
              }}
            >
              {g.label}
            </button>
          )
        })}
      </div>

      {/* Expressivity filter chips — language tiers with the OWL 2 profiles
          nested under OWL. Tiers set `language`; profiles set `profile`; the two
          axes are mutually exclusive in the UI (selecting one clears the other). */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginBottom: '0.6rem' }}>
        <span style={{ fontSize: 11, color: 'var(--text-dim)', marginRight: 2 }}>Expressivity:</span>
        {EXPRESSIVITY_OPTIONS.map(opt => {
          const active =
            opt.kind === 'all' ? (profile === '' && language === '')
            : opt.kind === 'tier' ? language === opt.value
            : profile === opt.value
          const activeColor =
            opt.kind === 'tier' ? TIER_BADGE[opt.value]?.color
            : opt.kind === 'profile' ? PROFILE_BADGE_COLORS[opt.value]?.color
            : 'var(--accent)'
          const onClick = () => {
            if (opt.kind === 'all') { setProfile(''); setLanguage('') }
            else if (opt.kind === 'tier') { setLanguage(opt.value); setProfile('') }
            else { setProfile(opt.value); setLanguage('') }
          }
          const title =
            opt.kind === 'all' ? 'Show all ontologies'
            : opt.kind === 'tier' ? `Show only ${opt.label} vocabularies`
            : `Show only ontologies that conform to OWL 2 ${opt.value.toUpperCase()}`
          return (
            <button
              key={opt.kind === 'all' ? 'all' : opt.value}
              onClick={onClick}
              title={title}
              style={{
                fontSize: 12, padding: '4px 12px', borderRadius: 20,
                border: '1px solid',
                borderColor: active ? (activeColor ?? 'var(--accent)') : 'var(--border)',
                cursor: 'pointer',
                background: active ? (activeColor ?? 'var(--accent)') : 'var(--bg-secondary)',
                color: active ? '#fff' : 'var(--text-dim)',
                fontWeight: active ? 700 : 500,
              }}
            >
              {opt.label}
            </button>
          )
        })}
      </div>

      {/* Language filter chips — collapsible: the row lists every repository
          language, which is long once a multilingual corpus (e.g. LOV) is loaded.
          Collapsed shows the top N by label count plus any selected language. */}
      {repoLangs.length > 0 && (() => {
        const COLLAPSED = 12
        const shown = langsExpanded
          ? repoLangs
          : repoLangs.filter((l, i) => i < COLLAPSED || langs.has(l.lang))
        const hidden = repoLangs.length - shown.length
        const moreStyle = { fontSize: 11, color: 'var(--text-dim)', padding: '2px 6px', cursor: 'pointer', background: 'none', border: 'none' } as const
        return (
          <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center', marginBottom: '1rem' }}>
            <span style={{ fontSize: 11, color: 'var(--text-dim)', marginRight: 2 }}>Lang:</span>
            {shown.map(({ lang, label_count }) => {
              const active = langs.has(lang)
              return (
                <button
                  key={lang}
                  onClick={() => toggleLang(lang)}
                  title={`${endonym(lang)} — ${label_count.toLocaleString()} labels`}
                  style={{
                    fontSize: 11, padding: '2px 8px', borderRadius: 20, cursor: 'pointer',
                    border: '1px solid rgba(86,182,194,0.35)',
                    background: 'rgba(86,182,194,0.10)',
                    color: 'var(--od-cyan)',
                    fontWeight: active ? 700 : 600,
                    opacity: active ? 1 : 0.65,
                  }}
                >
                  {lang || '—'}
                  <span style={{ opacity: 0.6, marginLeft: 4, fontWeight: 500 }}>{fmtCount(label_count)}</span>
                </button>
              )
            })}
            {!langsExpanded && hidden > 0 && (
              <button onClick={() => setLangsExpanded(true)} style={moreStyle}>
                +{hidden} more
              </button>
            )}
            {langsExpanded && repoLangs.length > COLLAPSED && (
              <button onClick={() => setLangsExpanded(false)} style={moreStyle}>
                show less
              </button>
            )}
            {langs.size > 0 && (
              <button
                onClick={() => setLangs(new Set())}
                style={{ fontSize: 11, color: 'var(--text-dim)', padding: '2px 6px' }}
              >
                clear
              </button>
            )}
          </div>
        )
      })()}

      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        background: 'var(--bg-secondary)', border: '1px solid var(--border)',
        borderRadius: 'var(--radius)', padding: '8px 12px', marginBottom: '1.5rem',
      }}>
        <span style={{ color: 'var(--text-dim)' }}>⌕</span>
        <input
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Filter by name, IRI, or description…"
          style={{
            flex: 1, background: 'none', border: 'none',
            color: 'var(--text)', fontSize: 'var(--font-size-base)', outline: 'none',
          }}
        />
        {query && (
          <button
            onClick={() => setQuery('')}
            style={{ color: 'var(--text-dim)', fontSize: 12, padding: '2px 6px' }}
          >
            ✕
          </button>
        )}
      </div>

      {/* Sort bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', marginBottom: '1rem' }}>
        <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)', marginRight: '0.25rem' }}>Sort:</span>
        {(['name', 'date'] as SortCol[]).map(col => {
          const active = sortCol === col
          const arrow = active ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ''
          const label = col === 'date' ? 'Last modified' : 'Name'
          return (
            <button
              key={col}
              onClick={() => handleSort(col)}
              style={{
                fontSize: 'var(--font-size-sm)',
                padding: '2px 8px', borderRadius: 4,
                border: '1px solid',
                borderColor: active ? 'var(--accent)' : 'var(--border)',
                color: active ? 'var(--accent)' : 'var(--text-dim)',
                background: 'transparent',
                cursor: 'pointer',
                fontWeight: active ? 600 : 400,
              }}
            >
              {label}{arrow}
            </button>
          )
        })}
      </div>

      {isLoading ? (
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>Loading…</p>
      ) : ontologies.length === 0 ? (
        <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
          {(query || group || profile || reuses) ? 'No ontologies match your filter.' : 'No ontologies loaded yet.'}
        </p>
      ) : (
        <>
          <p style={{ color: 'var(--text-dim)', fontSize: 11, margin: '0 0 0.5rem' }}>
            {(total ?? ontologies.length)} ontolog{(total ?? ontologies.length) === 1 ? 'y' : 'ies'}
            {(query || group || profile || reuses || langs.size > 0) && ' matching filter'}
          </p>
          <div ref={listRef} style={{ position: 'relative', height: rowVirtualizer.getTotalSize(), width: '100%' }}>
            {virtualItems.map(vi => {
              const o = ontologies[vi.index]
              return (
                <div
                  key={vi.key}
                  data-index={vi.index}
                  ref={rowVirtualizer.measureElement}
                  style={{
                    position: 'absolute', top: 0, left: 0, width: '100%',
                    transform: `translateY(${vi.start - rowVirtualizer.options.scrollMargin}px)`,
                  }}
                >
                  <OntologyRow o={o} profileEntry={profileByOntologyId.get(o.id)} />
                </div>
              )
            })}
          </div>
          {isFetchingNextPage && (
            <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', textAlign: 'center', padding: '0.75rem' }}>
              Loading more…
            </p>
          )}
        </>
      )}

      </>}
    </div>
  )
}
