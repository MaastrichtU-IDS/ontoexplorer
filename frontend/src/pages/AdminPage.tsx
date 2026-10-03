import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { useAdminOverview } from '../hooks/useAdminOverview'
import { useIsMobile } from '../hooks/useIsMobile'
import { api } from '../lib/api'
import type { PipelineStage, BulkAction, BulkActionResult } from '../lib/api'
import { JobsTable } from '../components/admin/JobsTable'
import { OntologyTable } from '../components/admin/OntologyTable'
import { WorkersPanel } from '../components/admin/WorkersPanel'
import { StarterQueriesPanel } from '../components/admin/StarterQueriesPanel'
import { MaintainerRequestsPanel } from '../components/admin/MaintainerRequestsPanel'
import { ReasonerProfilesPanel } from '../components/admin/ReasonerProfilesPanel'
import { SectionLabel, ServiceCard, UpdateState, ontologyDisplayName } from '../components/admin/shared'

type Tab = 'ontology' | 'sparql' | 'jobs' | 'maintainers' | 'reasoners'
const TAB_VALUES: Tab[] = ['ontology', 'sparql', 'jobs', 'maintainers', 'reasoners']
const TAB_LABELS: Record<Tab, string> = {
  ontology: 'Ontology',
  sparql: 'SPARQL queries',
  jobs: 'Jobs',
  maintainers: 'Maintainer requests',
  reasoners: 'Reasoners',
}

// Bulk pipeline actions for the admin ontology table's selection bar.
const BULK_ACTIONS: { action: BulkAction; label: string; icon: string; title: string }[] = [
  { action: 'index',          label: 'Re-index',       icon: '↺', title: 'Rebuild the search index for each selected ontology' },
  { action: 'embed',          label: 'Embed',          icon: '⬡', title: 'Generate vector embeddings for each selected ontology' },
  { action: 'reason',         label: 'Reason',         icon: '✸', title: 'Run the reasoner for each selected ontology' },
  { action: 'detect_profile', label: 'Detect profile', icon: '◇', title: 'Run OWL 2 profile detection for each selected ontology' },
  { action: 'ingest',         label: 'Re-ingest',      icon: '↑', title: 'Re-fetch each selected ontology from source (may create new versions)' },
]
const BULK_LABELS: Record<BulkAction, string> = Object.fromEntries(
  BULK_ACTIONS.map(b => [b.action, b.label])
) as Record<BulkAction, string>
// Re-ingest mutates the catalogue (re-fetches from source, can create new
// versions), so it always confirms; the recompute-only actions confirm only in
// bulk (> 50 selected).
const DESTRUCTIVE_ACTIONS = new Set<BulkAction>(['ingest'])
const BULK_CONFIRM_THRESHOLD = 50

export default function AdminPage() {
  const navigate = useNavigate()
  const { user, isLoading: authLoading } = useAuth()
  const { data, isLoading, dataUpdatedAt, refetch } = useAdminOverview()
  const { data: coverage } = useQuery({ queryKey: ['admin-coverage'], queryFn: () => api.admin.coverage() })
  // Clicking a status card filters the table to the ontologies MISSING that stage.
  const [stageFilter, setStageFilter] = useState<PipelineStage | null>(null)
  const isMobile = useIsMobile()
  const [searchParams, setSearchParams] = useSearchParams()
  const tabParam = searchParams.get('tab')
  const tab: Tab = (TAB_VALUES as string[]).includes(tabParam ?? '')
    ? (tabParam as Tab)
    : 'ontology'
  function setTab(next: Tab) {
    const params = new URLSearchParams(searchParams)
    if (next === 'ontology') params.delete('tab')
    else params.set('tab', next)
    setSearchParams(params)
  }

  const [secondsAgo, setSecondsAgo] = useState(0)
  const [updateStates, setUpdateStates] = useState<Record<string, UpdateState>>({})
  const [reindexStates, setReindexStates] = useState<Record<string, UpdateState>>({})
  // Bulk selection + action bar for the ontology table.
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkState, setBulkState] = useState<
    { action: BulkAction; status: 'working' } |
    { action: BulkAction; status: 'done'; result: BulkActionResult } |
    { action: BulkAction; status: 'error' } |
    null
  >(null)
  const [embedStates, setEmbedStates] = useState<Record<string, UpdateState>>({})
  const [profileStates, setProfileStates] = useState<Record<string, UpdateState>>({})
  const [versionProfileStates, setVersionProfileStates] = useState<Record<string, UpdateState>>({})
  const [recomputeStates, setRecomputeStates] = useState<Record<string, UpdateState>>({})
  const [pairDiffStates, setPairDiffStates] = useState<Record<string, UpdateState>>({})
  const [versionIndexStates, setVersionIndexStates] = useState<Record<string, UpdateState>>({})
  const [versionEmbedStates, setVersionEmbedStates] = useState<Record<string, UpdateState>>({})
  const [versionIngestStates, setVersionIngestStates] = useState<Record<string, UpdateState>>({})
  const [clearJobsState, setClearJobsState] = useState<'idle' | 'working' | 'error'>('idle')

  async function handleUpdate(ontologyId: string) {
    setUpdateStates(s => ({ ...s, [ontologyId]: 'queued' }))
    try { await api.admin.queueIngest(ontologyId) }
    catch { setUpdateStates(s => ({ ...s, [ontologyId]: 'error' })) }
  }

  async function handleReindex(ontologyId: string) {
    setReindexStates(s => ({ ...s, [ontologyId]: 'queued' }))
    try { await api.admin.queueIndex(ontologyId) }
    catch { setReindexStates(s => ({ ...s, [ontologyId]: 'error' })) }
  }

  async function handleEmbed(ontologyId: string) {
    setEmbedStates(s => ({ ...s, [ontologyId]: 'queued' }))
    try { await api.admin.queueEmbed(ontologyId) }
    catch { setEmbedStates(s => ({ ...s, [ontologyId]: 'error' })) }
  }

  async function handleDetectProfile(ontologyId: string) {
    setProfileStates(s => ({ ...s, [ontologyId]: 'queued' }))
    try { await api.admin.queueDetectProfile(ontologyId) }
    catch { setProfileStates(s => ({ ...s, [ontologyId]: 'error' })) }
  }

  async function handleVersionDetectProfile(versionId: string) {
    setVersionProfileStates(s => ({ ...s, [versionId]: 'queued' }))
    try { await api.admin.queueDetectProfileForVersion(versionId) }
    catch { setVersionProfileStates(s => ({ ...s, [versionId]: 'error' })) }
  }

  function toggleRow(ontologyId: string) {
    setSelected(s => {
      const n = new Set(s)
      if (n.has(ontologyId)) n.delete(ontologyId)
      else n.add(ontologyId)
      return n
    })
  }
  function setSelection(ontologyIds: string[], on: boolean) {
    setSelected(s => {
      const n = new Set(s)
      for (const id of ontologyIds) {
        if (on) n.add(id)
        else n.delete(id)
      }
      return n
    })
  }
  function clearSelection() { setSelected(new Set()) }

  async function handleBulk(action: BulkAction) {
    // Act only on selected rows that are actually visible under the current
    // stage filter, so a stale selection can't silently touch hidden rows.
    const ids = ontologyRows.filter(o => selected.has(o.id)).map(o => o.id)
    if (ids.length === 0) return
    const destructive = DESTRUCTIVE_ACTIONS.has(action)
    if (destructive || ids.length > BULK_CONFIRM_THRESHOLD) {
      const noun = ids.length === 1 ? 'ontology' : 'ontologies'
      const extra = destructive
        ? '\n\nThis re-fetches each one from source and may create new versions.'
        : ''
      if (!confirm(`${BULK_LABELS[action]} ${ids.length} ${noun}?${extra}`)) return
    }
    setBulkState({ action, status: 'working' })
    try {
      const result = await api.admin.bulkAction(action, ids)
      setBulkState({ action, status: 'done', result })
      await refetch()
    } catch {
      setBulkState({ action, status: 'error' })
    }
  }

  async function handleRecomputeAll(ontologyId: string) {
    setRecomputeStates(s => ({ ...s, [ontologyId]: 'queued' }))
    try { await api.admin.recomputeAllDiffs(ontologyId) }
    catch { setRecomputeStates(s => ({ ...s, [ontologyId]: 'error' })) }
  }

  async function handlePairDiff(fromVid: string, toVid: string) {
    const key = `${fromVid}->${toVid}`
    setPairDiffStates(s => ({ ...s, [key]: 'queued' }))
    try { await api.admin.queueDiff(fromVid, toVid) }
    catch { setPairDiffStates(s => ({ ...s, [key]: 'error' })) }
  }

  async function handleVersionIndex(versionId: string) {
    setVersionIndexStates(s => ({ ...s, [versionId]: 'queued' }))
    try { await api.admin.queueIndexForVersion(versionId) }
    catch { setVersionIndexStates(s => ({ ...s, [versionId]: 'error' })) }
  }
  async function handleVersionEmbed(versionId: string) {
    setVersionEmbedStates(s => ({ ...s, [versionId]: 'queued' }))
    try { await api.admin.queueEmbedForVersion(versionId) }
    catch { setVersionEmbedStates(s => ({ ...s, [versionId]: 'error' })) }
  }
  async function handleVersionIngest(versionId: string) {
    setVersionIngestStates(s => ({ ...s, [versionId]: 'queued' }))
    try { await api.admin.queueIngestForVersion(versionId) }
    catch { setVersionIngestStates(s => ({ ...s, [versionId]: 'error' })) }
  }

  async function handleClearJobs() {
    if (clearJobsState === 'working') return
    if (!confirm('Clear all completed and failed jobs from the recent-jobs log?')) return
    setClearJobsState('working')
    try {
      await api.admin.clearJobs()
      await refetch()
      setClearJobsState('idle')
    } catch {
      setClearJobsState('error')
    }
  }

  // Changing the status filter changes which rows are visible; reset the
  // selection so a bulk action never touches rows the admin can't see.
  useEffect(() => { setSelected(new Set()) }, [stageFilter])

  // Redirect non-admins after auth resolves
  useEffect(() => {
    if (!authLoading && user && !user.is_admin) {
      navigate('/')
    }
  }, [authLoading, user, navigate])

  // "Last updated Ns ago" counter
  useEffect(() => {
    if (!dataUpdatedAt) return
    const tick = () => setSecondsAgo(Math.floor((Date.now() - dataUpdatedAt) / 1000))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [dataUpdatedAt])

  if (authLoading || isLoading) {
    return <div style={{ padding: '2rem', color: 'var(--text-dim)' }}>Loading…</div>
  }
  if (!user?.is_admin) return null

  const s = data!.services

  const versionMap: Record<string, string> = {}
  for (const o of data!.ontologies) {
    versionMap[o.version_id] = ontologyDisplayName(o)
  }

  // Ontology ids missing each stage (from the coverage endpoint), for the cards
  // and the table filter.
  const missingByStage: Partial<Record<PipelineStage, Set<string>>> = {}
  if (coverage) {
    for (const st of coverage.stages) {
      missingByStage[st] = new Set(coverage.ontologies.filter(o => !o.stages[st]).map(o => o.ontology_id))
    }
  }
  const missingSet = stageFilter ? missingByStage[stageFilter] : undefined
  const ontologyRows = missingSet ? data!.ontologies.filter(o => missingSet.has(o.id)) : data!.ontologies
  const selectedVisibleCount = ontologyRows.reduce((n, o) => n + (selected.has(o.id) ? 1 : 0), 0)
  const bulkBusy = bulkState?.status === 'working'

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: isMobile ? '0.75rem 0.5rem' : '1.5rem 2rem' }}>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
        <span style={{ fontWeight: 600, fontSize: 16, color: 'var(--text)' }}>System Admin</span>
        <span style={{
          color: 'var(--green)', fontSize: 11,
          background: 'rgba(63,185,80,.1)', border: '1px solid rgba(63,185,80,.25)',
          padding: '1px 8px', borderRadius: 10,
        }}>
          ● live · refreshes every 10s
        </span>
        <div style={{ flex: 1 }} />
        <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
          Last updated {secondsAgo}s ago
        </span>
      </div>

      <SectionLabel>Service Health</SectionLabel>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 24 }}>
        <ServiceCard
          name="Postgres"
          status={s.postgres}
          description="Relational database: users, ontology catalog, versions, jobs, diffs, and pgvector term embeddings"
        />
        <ServiceCard
          name="Redis"
          status={s.redis}
          description="Celery broker + result/cache backend (search index, OWL-profile cache, ELK classification cache on DB 2)"
        />
        <ServiceCard
          name="MinIO"
          status={s.minio}
          description="Object storage for raw ontology artifacts and the imports closure cache"
        />
        <ServiceCard
          name="Metadata store"
          status={s.metadata_store}
          description="Embedded SPARQL store for FAIR metadata (DCAT + VoID + PROV-O) about each ontology version"
        />
        <ServiceCard
          name="Oxigraph"
          status={s.oxigraph}
          description="Embedded RDF triplestore (RocksDB) holding the asserted triples of every ingested ontology — one named graph per version"
        />
        <ServiceCard
          name="ELK"
          status={s.elk}
          description="OWL 2 EL reasoning microservice — classifies ontologies and supplies inferred subClassOf axioms"
        />
        <ServiceCard
          name="Workers"
          status={s.workers}
          description="Celery workers running the ingestion, indexing, embedding, reasoning, profile-detection and diff pipelines"
        />
        <ServiceCard
          name="Beat"
          status={s.beat}
          description="Celery Beat — scheduler for periodic tasks (hourly upstream-update poll, 15-min stale-diff refresh). Stale if no heartbeat for 120s."
        />
        <ServiceCard
          name="Entity Index"
          status={s.entity_index}
          description={`Postgres entity_index — flat per-entity table powering /search backend=pg. ~${s.entity_index_rows.toLocaleString()} rows (planner estimate) across all ready versions.`}
        />
        <ServiceCard
          name="Queue"
          status={s.celery_queue_depth}
          description="Depth of the Celery task queue in Redis (pending tasks waiting for a worker)"
        />
      </div>

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

      {tab === 'ontology' && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
            <SectionLabel style={{ margin: 0 }}>
              Ontology Pipeline ({ontologyRows.length}{stageFilter ? ` missing ${stageFilter}` : ''})
            </SectionLabel>
          </div>
          {coverage && (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 12 }}>
              {coverage.stages.map(st => {
                const c = coverage.counts[st]
                const active = stageFilter === st
                return (
                  <button
                    key={st}
                    onClick={() => setStageFilter(active ? null : st)}
                    title={`Filter to ontologies missing ${st}`}
                    style={{
                      textAlign: 'left', cursor: 'pointer', borderRadius: 6, padding: '6px 12px', minWidth: 116,
                      background: active ? 'var(--bg-secondary)' : 'none',
                      border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
                    }}
                  >
                    <div style={{ fontSize: 10, textTransform: 'capitalize', letterSpacing: 0.5, color: 'var(--text-dim)' }}>{st}</div>
                    <div style={{ fontSize: 13 }}>
                      <span style={{ color: 'var(--green)' }}>{c.done} ✓</span>
                      {c.missing > 0 && <span style={{ color: 'var(--text-dim)' }}> · {c.missing} missing</span>}
                    </div>
                  </button>
                )
              })}
              {stageFilter && (
                <button
                  onClick={() => setStageFilter(null)}
                  style={{ fontSize: 11, color: 'var(--text-dim)', background: 'none', border: 'none', cursor: 'pointer' }}
                >
                  clear filter ✕
                </button>
              )}
            </div>
          )}
          {selectedVisibleCount > 0 && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
              marginBottom: 12, padding: '8px 12px', borderRadius: 6,
              background: 'var(--bg-secondary)', border: '1px solid var(--accent)',
            }}>
              <span style={{ fontSize: 12, color: 'var(--text)', fontWeight: 600 }}>
                {selectedVisibleCount} selected
              </span>
              <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>— apply:</span>
              {BULK_ACTIONS.map(b => (
                <button
                  key={b.action}
                  onClick={() => handleBulk(b.action)}
                  disabled={bulkBusy}
                  title={b.title}
                  style={{
                    background: 'none',
                    border: `1px solid ${DESTRUCTIVE_ACTIONS.has(b.action) ? 'rgba(248,81,73,0.4)' : 'var(--border)'}`,
                    borderRadius: 4, cursor: bulkBusy ? 'default' : 'pointer',
                    color: DESTRUCTIVE_ACTIONS.has(b.action) ? 'var(--red)' : 'var(--text)',
                    fontSize: 11, padding: '4px 10px', opacity: bulkBusy ? 0.6 : 1,
                  }}
                >
                  {b.icon} {b.label}
                </button>
              ))}
              <div style={{ flex: 1 }} />
              {bulkState?.status === 'working' && (
                <span style={{ color: 'var(--orange)', fontSize: 11 }}>
                  queuing {BULK_LABELS[bulkState.action]}…
                </span>
              )}
              {bulkState?.status === 'done' && (() => {
                const r = bulkState.result
                const errCount = Object.keys(r.errors).length
                return (
                  <span style={{ color: errCount ? 'var(--orange)' : 'var(--green)', fontSize: 11 }}
                        title={errCount ? Object.entries(r.errors).map(([id, e]) => `${id}: ${e}`).join('\n') : undefined}>
                    ✓ {BULK_LABELS[r.action]}: {r.queued.length} queued
                    {r.skipped.length ? ` · ${r.skipped.length} skipped` : ''}
                    {errCount ? ` · ${errCount} failed` : ''}
                  </span>
                )
              })()}
              {bulkState?.status === 'error' && (
                <span style={{ color: 'var(--red)', fontSize: 11 }}>
                  ✕ {BULK_LABELS[bulkState.action]} failed
                </span>
              )}
              <button
                onClick={clearSelection}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-dim)', fontSize: 11 }}
              >
                clear ✕
              </button>
            </div>
          )}
          <OntologyTable
            rows={ontologyRows}
            selected={selected}
            onToggleRow={toggleRow}
            onSetSelection={setSelection}
            updateStates={updateStates}
            onUpdate={handleUpdate}
            reindexStates={reindexStates}
            onReindex={handleReindex}
            embedStates={embedStates}
            onEmbed={handleEmbed}
            onReasoned={refetch}
            profileStates={profileStates}
            onDetectProfile={handleDetectProfile}
            versionProfileStates={versionProfileStates}
            onVersionDetectProfile={handleVersionDetectProfile}
            recomputeStates={recomputeStates}
            onRecomputeAll={handleRecomputeAll}
            pairDiffStates={pairDiffStates}
            onPairDiff={handlePairDiff}
            versionIndexStates={versionIndexStates}
            onVersionIndex={handleVersionIndex}
            versionEmbedStates={versionEmbedStates}
            onVersionEmbed={handleVersionEmbed}
            versionIngestStates={versionIngestStates}
            onVersionIngest={handleVersionIngest}
          />
        </>
      )}

      {tab === 'sparql' && (
        <>
          <SectionLabel>Starter Queries</SectionLabel>
          <StarterQueriesPanel />
        </>
      )}

      {tab === 'jobs' && (
        <>
          <SectionLabel>Workers</SectionLabel>
          <div style={{ marginBottom: 24 }}>
            <WorkersPanel versionMap={versionMap} />
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
            <SectionLabel style={{ margin: 0 }}>Recent Jobs</SectionLabel>
            <div style={{ flex: 1 }} />
            <button
              onClick={handleClearJobs}
              disabled={clearJobsState === 'working'}
              title="Delete completed and failed job rows (keeps running and pending)"
              style={{
                background: clearJobsState === 'error' ? 'rgba(248,81,73,0.1)' : 'none',
                border: `1px solid ${clearJobsState === 'error' ? 'rgba(248,81,73,0.3)' : 'var(--border)'}`,
                borderRadius: 4,
                cursor: clearJobsState === 'working' ? 'default' : 'pointer',
                color: clearJobsState === 'error' ? 'var(--red)' : clearJobsState === 'working' ? 'var(--orange)' : 'var(--text-dim)',
                fontSize: 11, padding: '4px 12px',
                opacity: clearJobsState === 'working' ? 0.7 : 1,
              }}
            >
              {clearJobsState === 'working' ? 'clearing…' : clearJobsState === 'error' ? '✕ retry clear' : '✕ Clear recent jobs'}
            </button>
          </div>
          <JobsTable jobs={data!.jobs} />
        </>
      )}

      {tab === 'maintainers' && (
        <MaintainerRequestsPanel />
      )}

      {tab === 'reasoners' && (
        <ReasonerProfilesPanel />
      )}

    </div>
  )
}
