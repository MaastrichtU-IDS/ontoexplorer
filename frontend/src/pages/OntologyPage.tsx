import { useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useOntologies } from '../hooks/useOntologies'
import { useVersions } from '../hooks/useVersions'
import { slugFromIri, OntologyVersion, api } from '../lib/api'
import ClassTree from '../components/ClassTree'
import TermPanel from '../components/TermPanel'
import ResizeHandle from '../components/ResizeHandle'

const PANE_MIN = 220
const PANE_MAX = 640
const PANE_DEFAULT = 300

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
      borderRadius: 'var(--radius)', padding: '12px 16px', minWidth: 120,
    }}>
      <div style={{ color: 'var(--text)', fontSize: 20, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
        {typeof value === 'number' ? value.toLocaleString() : value}
      </div>
      <div style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: 2 }}>{label}</div>
    </div>
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

      {/* ── Metadata ── */}
      <h3 style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12 }}>
        Metadata
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

      {/* ── Statistics ── */}
      <h3 style={{ color: 'var(--text-dim)', fontSize: 11, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12 }}>
        Statistics
      </h3>
      {statsLoading ? (
        <div style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>Loading stats…</div>
      ) : stats ? (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
          <StatCard label="Triples" value={stats.triple_count} />
          <StatCard label="Classes" value={stats.class_count} />
          <StatCard label="Properties" value={stats.property_count} />
          {stats.individual_count > 0 && (
            <StatCard label="Individuals" value={stats.individual_count} />
          )}
          {stats.index_meta?.indexed_at && (
            <StatCard label="Indexed" value={new Date(stats.index_meta.indexed_at).toLocaleDateString()} />
          )}
        </div>
      ) : null}
    </div>
  )
}

// ── Collapsible section ───────────────────────────────────────────────────────

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

// ── Main page ─────────────────────────────────────────────────────────────────

export default function OntologyPage() {
  const { slug, version } = useParams<{ slug: string; version?: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
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
  }

  function resetToMeta() {
    setSearchParams({})
  }

  if (!ontologiesLoading && !ontology) {
    return (
      <div style={{ padding: '2rem', color: 'var(--text-dim)' }}>
        Ontology <code style={{ color: 'var(--accent)' }}>{slug}</code> not found.
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - var(--nav-height))', overflow: 'hidden' }}>

      {/* ── Left pane ── */}
      <div style={{
        width: paneWidth, flexShrink: 0,
        display: 'flex', flexDirection: 'column',
        background: 'var(--bg-secondary)', borderRight: '1px solid var(--border)',
        overflow: 'hidden',
      }}>

        {/* Clickable ontology name */}
        <div style={{ padding: '10px', borderBottom: '1px solid var(--border)' }}>
          <button
            onClick={resetToMeta}
            style={{
              background: 'none', border: 'none', cursor: 'pointer', padding: 0,
              color: 'var(--accent)', fontWeight: 600, fontSize: 'var(--font-size-sm)',
              textAlign: 'left',
            }}
          >
            {slug}
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
                <option key={v.id} value={v.id}>
                  {v.version_iri ?? v.id}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Scrollable hierarchy area */}
        {oid && activeVid ? (
          <div style={{ flex: 1, overflow: 'auto' }}>
            <CollapsibleSection label="Classes" defaultOpen={true}>
              <ClassTree
                ontologyId={oid}
                versionId={activeVid}
                selectedIri={selectedTermIri}
                onSelect={selectTerm}
                entityType="class"
              />
            </CollapsibleSection>
            <CollapsibleSection label="Properties" defaultOpen={false}>
              <ClassTree
                ontologyId={oid}
                versionId={activeVid}
                selectedIri={selectedTermIri}
                onSelect={selectTerm}
                entityType="property"
              />
            </CollapsibleSection>
          </div>
        ) : (
          <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
            {versionsLoading ? 'Loading…' : 'No versions available'}
          </div>
        )}
      </div>

      {/* Resize handle */}
      <ResizeHandle onDelta={handleDelta} />

      {/* ── Right pane (single column) ── */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {oid && activeVid && selectedTermIri ? (
          <TermPanel
            ontologyId={oid}
            versionId={activeVid}
            termIri={selectedTermIri}
            singlePane={true}
          />
        ) : (
          <OntologyMeta iri={ontology?.iri ?? ''} version={activeVersion} />
        )}
      </div>

    </div>
  )
}
