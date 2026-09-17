import { useState, useMemo, memo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useOntologySearch } from '../hooks/useOntologySearch'
import { useRepositoryLanguages } from '../hooks/useRepositoryLanguages'
import { useIsMobile } from '../hooks/useIsMobile'
import { api, Ontology, OwlProfileFleetEntry, ProfileName, slugFromIri } from '../lib/api'
import Coverage from './Coverage'
import OwlProfile from './OwlProfile'
import Compare from './Compare'
import { Reuse } from './Reuse'

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
    <tr
      className="ontology-row"
      onClick={() => latest && navigate(`/ontologies/${o.shortname ?? slugFromIri(o.iri)}`)}
      style={{ cursor: latest ? 'pointer' : 'default', borderBottom: '2px solid var(--border)' }}
    >
      <td style={{ padding: '10px 12px' }}>
        {/* Name · IRI chip · group badges */}
        {o.label && (
          <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text)', marginBottom: 2 }}>
            {o.label}
          </div>
        )}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ color: 'var(--accent)', fontWeight: 500 }}>{displayName(o)}</span>
          <IriChip iri={o.iri} />
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
      </td>
    </tr>
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

const PROFILES: { value: '' | ProfileName; label: string }[] = [
  { value: '',   label: 'All' },
  { value: 'dl', label: 'OWL 2 DL' },
  { value: 'el', label: 'OWL 2 EL' },
  { value: 'ql', label: 'OWL 2 QL' },
  { value: 'rl', label: 'OWL 2 RL' },
]

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
  const [langs, setLangs] = useState<Set<string>>(new Set())
  const [sortCol, setSortCol] = useState<SortCol>('name')
  const [sortDir, setSortDir] = useState<SortDir>('asc')
  const reuses = searchParams.get('reuses') ?? undefined
  const { data, isLoading } = useOntologySearch(query, group || undefined, profile || undefined, reuses)
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

  const ontologies = useMemo(() => {
    const list = data?.ontologies ?? []
    const langFiltered = langs.size === 0
      ? list
      : list.filter(o => (o.languages ?? []).some(l => langs.has(l.lang)))
    return [...langFiltered].sort((a, b) => {
      const cmp = sortCol === 'name'
        ? displayName(a).localeCompare(displayName(b))
        : new Date(a.latest_version?.created_at ?? a.created_at).getTime()
          - new Date(b.latest_version?.created_at ?? b.created_at).getTime()
      return sortDir === 'asc' ? cmp : -cmp
    })
  }, [data, langs, sortCol, sortDir])

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

      {tab === 'coverage' && <Coverage />}
      {tab === 'profiles' && <OwlProfile />}
      {tab === 'compare' && <Compare />}
      {tab === 'reuse' && <Reuse />}
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

      {/* OWL 2 profile filter chips */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginBottom: '0.6rem' }}>
        <span style={{ fontSize: 11, color: 'var(--text-dim)', marginRight: 2 }}>OWL Profile:</span>
        {PROFILES.map(p => {
          const active = profile === p.value
          const c = p.value ? PROFILE_BADGE_COLORS[p.value] : null
          return (
            <button
              key={p.value}
              onClick={() => setProfile(p.value)}
              title={p.value ? `Show only ontologies that conform to OWL 2 ${p.value.toUpperCase()}` : 'Show all ontologies'}
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
              {p.label}
            </button>
          )
        })}
      </div>

      {/* Language filter chips */}
      {repoLangs.length > 0 && (
        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center', marginBottom: '1rem' }}>
          <span style={{ fontSize: 11, color: 'var(--text-dim)', marginRight: 2 }}>Lang:</span>
          {repoLangs.map(({ lang, label_count }) => {
            const active = langs.has(lang)
            return (
              <button
                key={lang}
                onClick={() => toggleLang(lang)}
                title={`${label_count.toLocaleString()} labels`}
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
              </button>
            )
          })}
          {langs.size > 0 && (
            <button
              onClick={() => setLangs(new Set())}
              style={{ fontSize: 11, color: 'var(--text-dim)', padding: '2px 6px' }}
            >
              clear
            </button>
          )}
        </div>
      )}

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
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <tbody>
            {ontologies.map(o => (
              <OntologyRow key={o.id} o={o} profileEntry={profileByOntologyId.get(o.id)} />
            ))}
          </tbody>
        </table>
      )}

      <p style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: '1rem' }}>
        {ontologies.length} ontolog{ontologies.length === 1 ? 'y' : 'ies'}
        {(query || group || profile || reuses || langs.size > 0) && ' matching filter'}
      </p>
      </>}
    </div>
  )
}
