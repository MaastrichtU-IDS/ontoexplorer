import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../lib/api'

export default function Dashboard() {
  const [iri, setIri] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'iri' | 'url' | 'paste'>('iri')

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['ontologies'],
    queryFn: () => api.ontologies.list(),
  })

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setMessage(null)
    try {
      const result = activeTab === 'iri'
        ? await api.ontologies.submitByIri(iri)
        : await api.ontologies.submitByUrl(iri)
      setMessage(`Queued — task ID: ${result.task_id}`)
      setIri('')
      setTimeout(() => refetch(), 2000)
    } catch (err: unknown) {
      setMessage(`Error: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setSubmitting(false)
    }
  }

  const tabs: { key: 'iri' | 'url' | 'paste'; label: string }[] = [
    { key: 'iri', label: 'By IRI' },
    { key: 'url', label: 'By URL' },
    { key: 'paste', label: 'Upload / Paste' },
  ]

  return (
    <div>
      <h1 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '1.5rem' }}>My Ontologies</h1>

      {/* Add Ontology */}
      <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, padding: '1.25rem', marginBottom: '2rem' }}>
        <h2 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '0.75rem' }}>Add Ontology</h2>
        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.75rem' }}>
          {tabs.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              style={{
                padding: '0.35rem 0.75rem', borderRadius: 4, border: '1px solid #e2e8f0',
                background: activeTab === key ? '#2563eb' : '#fff',
                color: activeTab === key ? '#fff' : '#475569',
                fontWeight: activeTab === key ? 600 : 400,
              }}
            >
              {label}
            </button>
          ))}
        </div>

        {activeTab === 'paste' ? (
          <p style={{ color: '#64748b', fontSize: '0.9rem' }}>
            File upload is available via the REST API: <code>POST /api/v1/ontologies</code> with multipart form data.
          </p>
        ) : (
          <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '0.5rem' }}>
            <input
              value={iri}
              onChange={e => setIri(e.target.value)}
              placeholder={activeTab === 'iri' ? 'https://purl.obolibrary.org/obo/go.owl' : 'https://example.com/ontology.ttl'}
              style={{ flex: 1, padding: '0.5rem 0.75rem', border: '1px solid #e2e8f0', borderRadius: 6 }}
              required
            />
            <button
              type="submit"
              disabled={submitting}
              style={{ padding: '0.5rem 1rem', background: '#2563eb', color: '#fff', border: 'none', borderRadius: 6, fontWeight: 600 }}
            >
              {submitting ? 'Submitting…' : 'Add'}
            </button>
          </form>
        )}
        {message && <p style={{ marginTop: '0.5rem', color: message.startsWith('Error') ? '#dc2626' : '#16a34a', fontSize: '0.875rem' }}>{message}</p>}
      </div>

      {/* Ontology table */}
      {isLoading ? (
        <p style={{ color: '#64748b' }}>Loading…</p>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, overflow: 'hidden' }}>
          <thead style={{ background: '#f8fafc' }}>
            <tr>
              {['IRI', 'Added'].map(h => (
                <th key={h} style={{ padding: '0.75rem 1rem', textAlign: 'left', fontSize: '0.8rem', fontWeight: 600, color: '#64748b', borderBottom: '1px solid #e2e8f0' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(data?.ontologies ?? []).map(o => (
              <tr key={o.id} style={{ borderBottom: '1px solid #f1f5f9' }}>
                <td style={{ padding: '0.75rem 1rem', fontSize: '0.875rem' }}><code>{o.iri}</code></td>
                <td style={{ padding: '0.75rem 1rem', fontSize: '0.875rem', color: '#64748b' }}>{new Date(o.created_at).toLocaleDateString()}</td>
              </tr>
            ))}
            {!data?.ontologies.length && (
              <tr><td colSpan={2} style={{ padding: '1.5rem', textAlign: 'center', color: '#94a3b8' }}>No ontologies yet. Add one above.</td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  )
}
