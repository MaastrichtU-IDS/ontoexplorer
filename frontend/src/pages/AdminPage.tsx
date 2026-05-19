import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { useAdminOverview } from '../hooks/useAdminOverview'
import { api } from '../lib/api'
import { JobsTable } from '../components/admin/JobsTable'
import { OntologyTable } from '../components/admin/OntologyTable'
import { WorkersPanel } from '../components/admin/WorkersPanel'
import { SectionLabel, ServiceCard, UpdateState, ontologyDisplayName } from '../components/admin/shared'

export default function AdminPage() {
  const navigate = useNavigate()
  const { user, isLoading: authLoading } = useAuth()
  const { data, isLoading, dataUpdatedAt } = useAdminOverview()
  const [secondsAgo, setSecondsAgo] = useState(0)
  const [updateStates, setUpdateStates] = useState<Record<string, UpdateState>>({})
  const [reindexStates, setReindexStates] = useState<Record<string, UpdateState>>({})
  const [reindexAllState, setReindexAllState] = useState<'idle' | 'queued' | 'error'>('idle')
  const [embedStates, setEmbedStates] = useState<Record<string, UpdateState>>({})
  const [reasonStates, setReasonStates] = useState<Record<string, UpdateState>>({})
  const [recomputeStates, setRecomputeStates] = useState<Record<string, UpdateState>>({})
  const [pairDiffStates, setPairDiffStates] = useState<Record<string, UpdateState>>({})
  const [versionIndexStates, setVersionIndexStates] = useState<Record<string, UpdateState>>({})
  const [versionEmbedStates, setVersionEmbedStates] = useState<Record<string, UpdateState>>({})
  const [versionReasonStates, setVersionReasonStates] = useState<Record<string, UpdateState>>({})
  const [versionIngestStates, setVersionIngestStates] = useState<Record<string, UpdateState>>({})

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
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '1.5rem 2rem' }}>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
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
        <ServiceCard name="Postgres" status={s.postgres} />
        <ServiceCard name="Redis" status={s.redis} />
        <ServiceCard name="MinIO" status={s.minio} />
        <ServiceCard name="ELK" status={s.elk} />
        <ServiceCard name="Queue" status={s.celery_queue_depth} />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
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
      <div style={{ marginBottom: 24 }}>
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
      </div>

      <SectionLabel>Workers</SectionLabel>
      <div style={{ marginBottom: 24 }}>
        <WorkersPanel versionMap={versionMap} />
      </div>

      <SectionLabel>Recent Jobs</SectionLabel>
      <JobsTable jobs={data!.jobs} />

    </div>
  )
}
