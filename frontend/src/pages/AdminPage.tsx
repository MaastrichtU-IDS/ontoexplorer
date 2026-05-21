import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { useAdminOverview } from '../hooks/useAdminOverview'
import { useIsMobile } from '../hooks/useIsMobile'
import { api } from '../lib/api'
import { JobsTable } from '../components/admin/JobsTable'
import { OntologyTable } from '../components/admin/OntologyTable'
import { WorkersPanel } from '../components/admin/WorkersPanel'
import { StarterQueriesPanel } from '../components/admin/StarterQueriesPanel'
import { SectionLabel, ServiceCard, UpdateState, ontologyDisplayName } from '../components/admin/shared'

type Tab = 'ontology' | 'sparql' | 'jobs'
const TAB_VALUES: Tab[] = ['ontology', 'sparql', 'jobs']
const TAB_LABELS: Record<Tab, string> = {
  ontology: 'Ontology',
  sparql: 'SPARQL queries',
  jobs: 'Jobs',
}

export default function AdminPage() {
  const navigate = useNavigate()
  const { user, isLoading: authLoading } = useAuth()
  const { data, isLoading, dataUpdatedAt, refetch } = useAdminOverview()
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
  const [reindexAllState, setReindexAllState] = useState<'idle' | 'queued' | 'error'>('idle')
  const [embedStates, setEmbedStates] = useState<Record<string, UpdateState>>({})
  const [reasonStates, setReasonStates] = useState<Record<string, UpdateState>>({})
  const [profileStates, setProfileStates] = useState<Record<string, UpdateState>>({})
  const [versionProfileStates, setVersionProfileStates] = useState<Record<string, UpdateState>>({})
  const [recomputeStates, setRecomputeStates] = useState<Record<string, UpdateState>>({})
  const [pairDiffStates, setPairDiffStates] = useState<Record<string, UpdateState>>({})
  const [versionIndexStates, setVersionIndexStates] = useState<Record<string, UpdateState>>({})
  const [versionEmbedStates, setVersionEmbedStates] = useState<Record<string, UpdateState>>({})
  const [versionReasonStates, setVersionReasonStates] = useState<Record<string, UpdateState>>({})
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

  async function handleReason(ontologyId: string) {
    setReasonStates(s => ({ ...s, [ontologyId]: 'queued' }))
    try { await api.admin.queueReason(ontologyId) }
    catch { setReasonStates(s => ({ ...s, [ontologyId]: 'error' })) }
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

  async function handleReindexAll() {
    setReindexAllState('queued')
    try { await api.admin.reindexAll() }
    catch { setReindexAllState('error') }
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
  async function handleVersionReason(versionId: string) {
    setVersionReasonStates(s => ({ ...s, [versionId]: 'queued' }))
    try { await api.admin.queueReasonForVersion(versionId) }
    catch { setVersionReasonStates(s => ({ ...s, [versionId]: 'error' })) }
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

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: isMobile ? '0.75rem 0.5rem' : '1.5rem 2rem' }}>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
        <span style={{ fontWeight: 600, fontSize: 16, color: 'var(--text)' }}>System Admin</span>
        <span style={{
          color: '#3fb950', fontSize: 11,
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
          name="Fuseki"
          status={s.fuseki}
          description="External SPARQL endpoint for FAIR metadata (DCAT + VoID + PROV-O) about each ontology version"
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
          description={`Postgres entity_index — flat per-entity table powering /search backend=pg. ${s.entity_index_rows.toLocaleString()} rows across all ready versions. Drifts when Redis and Postgres entity counts diverge > 5% on any version.`}
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
            <SectionLabel style={{ margin: 0 }}>Ontology Pipeline ({data!.ontologies.length})</SectionLabel>
            <div style={{ flex: 1 }} />
            <button
              onClick={handleReindexAll}
              disabled={reindexAllState === 'queued'}
              title="Queue index_ontology for every ingested version (rebuilds search index and deprecated-term filter)"
              style={{
                background: reindexAllState === 'error' ? 'rgba(248,81,73,0.1)' : 'none',
                border: `1px solid ${reindexAllState === 'error' ? 'rgba(248,81,73,0.3)' : 'var(--border)'}`,
                borderRadius: 4, cursor: reindexAllState === 'queued' ? 'default' : 'pointer',
                color: reindexAllState === 'error' ? '#f85149' : reindexAllState === 'queued' ? '#ffa657' : 'var(--text-dim)',
                fontSize: 11, padding: '4px 12px',
                opacity: reindexAllState === 'queued' ? 0.7 : 1,
              }}
            >
              {reindexAllState === 'queued' ? '↑ queuing…' : reindexAllState === 'error' ? '✕ retry re-index all' : '↺ Re-index all'}
            </button>
          </div>
          <OntologyTable
            rows={data!.ontologies}
            updateStates={updateStates}
            onUpdate={handleUpdate}
            reindexStates={reindexStates}
            onReindex={handleReindex}
            embedStates={embedStates}
            onEmbed={handleEmbed}
            reasonStates={reasonStates}
            onReason={handleReason}
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
            versionReasonStates={versionReasonStates}
            onVersionReason={handleVersionReason}
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
                color: clearJobsState === 'error' ? '#f85149' : clearJobsState === 'working' ? '#ffa657' : 'var(--text-dim)',
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

    </div>
  )
}
