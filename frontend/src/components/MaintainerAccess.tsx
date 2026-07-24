import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../hooks/useAuth'
import { api, MaintainerRequest } from '../lib/api'

const STATUS_COLOR: Record<string, string> = {
  pending: '#f0883e',
  approved: '#3fb950',
  denied: 'var(--error, #e06c75)',
}

const card: React.CSSProperties = {
  background: 'var(--bg-secondary)', border: '1px solid var(--border)',
  borderRadius: 'var(--radius)', padding: '1.25rem 1.5rem', marginTop: '1.5rem',
}
const label: React.CSSProperties = {
  fontSize: '0.875rem', fontWeight: 600, color: 'var(--text)',
  textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.75rem',
}
const ta: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box', background: 'var(--bg)',
  border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
  color: 'var(--text)', fontSize: 'var(--font-size-sm)', padding: '6px 8px', resize: 'vertical',
}
const btn: React.CSSProperties = {
  padding: '6px 16px', borderRadius: 'var(--radius-sm)', background: 'var(--accent)',
  border: 'none', color: '#0a0f1a', fontSize: 'var(--font-size-sm)', fontWeight: 600, cursor: 'pointer',
}

export default function MaintainerAccess() {
  const { user } = useAuth()
  const qc = useQueryClient()
  const [uploaderNote, setUploaderNote] = useState('')
  const [ontoId, setOntoId] = useState('')
  const [ontoNote, setOntoNote] = useState('')
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null)

  const { data: mine } = useQuery({ queryKey: ['maintainers', 'mine'], queryFn: api.maintainers.mine })
  const { data: ontos } = useQuery({ queryKey: ['ontologies'], queryFn: () => api.ontologies.list() })

  const create = useMutation({
    mutationFn: (body: { request_type: 'ontology' | 'uploader'; ontology_id?: string; note?: string }) =>
      api.maintainers.request(body),
    onSuccess: () => {
      setMsg({ text: 'Request submitted — an admin will review it.', ok: true })
      setUploaderNote(''); setOntoNote(''); setOntoId('')
      qc.invalidateQueries({ queryKey: ['maintainers', 'mine'] })
    },
    onError: (e) => setMsg({ text: (e as Error)?.message || 'Could not submit request', ok: false }),
  })

  if (!user) return null

  const requests: MaintainerRequest[] = mine?.requests ?? []
  const canUpload = !!user.is_admin || !!user.is_uploader
  const pendingUploader = requests.some(r => r.request_type === 'uploader' && r.status === 'pending')

  return (
    <div style={card}>
      <h2 style={{ ...label, marginBottom: '0.25rem' }}>Maintainer access</h2>
      <p style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)', marginBottom: '1.25rem' }}>
        Request permission to add ontologies, or to maintain an existing one. Requests are reviewed by an admin.
      </p>

      {/* Upload access */}
      <div style={{ marginBottom: '1.5rem' }}>
        <div style={{ fontWeight: 600, color: 'var(--text)', fontSize: 'var(--font-size-sm)', marginBottom: 6 }}>
          Add new ontologies
        </div>
        {canUpload ? (
          <p style={{ fontSize: 'var(--font-size-sm)', color: '#3fb950' }}>
            ● You can add ontologies{user.is_admin ? ' (admin)' : ''}.
          </p>
        ) : pendingUploader ? (
          <p style={{ fontSize: 'var(--font-size-sm)', color: '#f0883e' }}>● Request pending review.</p>
        ) : (
          <>
            <textarea
              placeholder="Why do you need to add ontologies? (rationale for the admin)"
              value={uploaderNote} onChange={e => setUploaderNote(e.target.value)} rows={2} style={ta}
            />
            <button
              style={{ ...btn, marginTop: 8, opacity: create.isPending ? 0.7 : 1 }}
              disabled={create.isPending}
              onClick={() => create.mutate({ request_type: 'uploader', note: uploaderNote || undefined })}
            >Request upload access</button>
          </>
        )}
      </div>

      {/* Maintain existing ontology */}
      <div>
        <div style={{ fontWeight: 600, color: 'var(--text)', fontSize: 'var(--font-size-sm)', marginBottom: 6 }}>
          Maintain an existing ontology
        </div>
        <select
          value={ontoId} onChange={e => setOntoId(e.target.value)}
          style={{ ...ta, marginBottom: 8, cursor: 'pointer' } as React.CSSProperties}
        >
          <option value="">Select an ontology…</option>
          {(ontos?.ontologies ?? []).map(o => (
            <option key={o.id} value={o.id}>{o.shortname || o.iri}</option>
          ))}
        </select>
        <textarea
          placeholder="Why should you maintain this ontology? (rationale for the admin)"
          value={ontoNote} onChange={e => setOntoNote(e.target.value)} rows={2} style={ta}
        />
        <button
          style={{ ...btn, marginTop: 8, opacity: (!ontoId || create.isPending) ? 0.6 : 1 }}
          disabled={!ontoId || create.isPending}
          onClick={() => create.mutate({ request_type: 'ontology', ontology_id: ontoId, note: ontoNote || undefined })}
        >Request to maintain</button>
      </div>

      {msg && (
        <p style={{ marginTop: '0.75rem', fontSize: 'var(--font-size-sm)', color: msg.ok ? '#3fb950' : 'var(--error, #e06c75)' }}>
          {msg.text}
        </p>
      )}

      {/* My requests */}
      {requests.length > 0 && (
        <div style={{ marginTop: '1.5rem' }}>
          <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)', marginBottom: 8 }}>Your requests</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {requests.map(r => (
              <div key={r.id} style={{
                display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline',
                padding: '6px 10px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'var(--bg)',
              }}>
                <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text)' }}>
                  {r.request_type === 'uploader' ? 'Upload access' : `Maintain ${r.ontology_shortname || r.ontology_iri || r.ontology_id}`}
                  {r.decision_note ? <span style={{ color: 'var(--text-dim)' }}> — {r.decision_note}</span> : null}
                </span>
                <span style={{ fontSize: '0.72rem', fontWeight: 700, color: STATUS_COLOR[r.status], textTransform: 'uppercase' }}>
                  {r.status}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
