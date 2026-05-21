import { useState, useRef } from 'react'
import { api, ImportStartersResponse } from '../../lib/api'

export function StarterQueriesPanel() {
  const [pasteText, setPasteText] = useState('')
  const [urlText, setUrlText] = useState('')
  const fileRef = useRef<HTMLInputElement | null>(null)
  const [result, setResult] = useState<ImportStartersResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function run<T extends () => Promise<ImportStartersResponse>>(fn: T) {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const r = await fn()
      setResult(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Import failed')
    } finally {
      setBusy(false)
    }
  }

  function handlePaste() {
    if (!pasteText.trim()) return
    run(() => api.admin.importStarters({ text: pasteText }))
  }

  function handleUpload() {
    const file = fileRef.current?.files?.[0]
    if (!file) return
    run(() => api.admin.importStarters({ file }))
  }

  function handleUrl() {
    if (!urlText.trim()) return
    run(() => api.admin.importStarters({ source_url: urlText.trim() }))
  }

  return (
    <div style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', borderRadius: 6, padding: '0.75rem 1rem', display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>Starter Queries — Import</div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <label htmlFor="starter-paste" style={{ fontSize: 11, color: 'var(--text-dim)' }}>Paste (JSON library or .rq)</label>
        <textarea
          id="starter-paste"
          aria-label="Paste"
          value={pasteText}
          onChange={e => setPasteText(e.target.value)}
          rows={4}
          placeholder='{ "starters": [...] }  OR  # @name …'
          style={{ width: '100%', boxSizing: 'border-box', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 4, padding: '6px 8px', fontSize: 11, color: 'var(--text)', fontFamily: 'monospace' }}
        />
        <button
          onClick={handlePaste}
          disabled={busy || !pasteText.trim()}
          style={{ alignSelf: 'flex-start', background: 'var(--accent)', color: 'var(--bg)', border: 'none', borderRadius: 4, padding: '4px 10px', fontSize: 11, fontWeight: 600, cursor: busy ? 'default' : 'pointer', opacity: busy || !pasteText.trim() ? 0.5 : 1 }}
        >Import paste</button>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <label htmlFor="starter-upload" style={{ fontSize: 11, color: 'var(--text-dim)' }}>Upload (.json or .rq)</label>
        <input
          id="starter-upload"
          aria-label="Upload"
          type="file"
          ref={fileRef}
          accept=".json,.rq"
          style={{ fontSize: 11, color: 'var(--text-dim)' }}
        />
        <button
          onClick={handleUpload}
          disabled={busy}
          style={{ alignSelf: 'flex-start', background: 'var(--accent)', color: 'var(--bg)', border: 'none', borderRadius: 4, padding: '4px 10px', fontSize: 11, fontWeight: 600, cursor: busy ? 'default' : 'pointer', opacity: busy ? 0.5 : 1 }}
        >Import file</button>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <label htmlFor="starter-url" style={{ fontSize: 11, color: 'var(--text-dim)' }}>URL (https://… or http://localhost)</label>
        <input
          id="starter-url"
          aria-label="URL"
          type="text"
          value={urlText}
          onChange={e => setUrlText(e.target.value)}
          placeholder="https://example.org/starters.json"
          style={{ width: '100%', boxSizing: 'border-box', background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 4, padding: '4px 8px', fontSize: 11, color: 'var(--text)' }}
        />
        <button
          onClick={handleUrl}
          disabled={busy || !urlText.trim()}
          style={{ alignSelf: 'flex-start', background: 'var(--accent)', color: 'var(--bg)', border: 'none', borderRadius: 4, padding: '4px 10px', fontSize: 11, fontWeight: 600, cursor: busy ? 'default' : 'pointer', opacity: busy || !urlText.trim() ? 0.5 : 1 }}
        >Import URL</button>
      </div>

      {result && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          Imported {result.created} · Skipped {result.skipped}
          {result.errors.length > 0 && (
            <> · {result.errors.length} error{result.errors.length === 1 ? '' : 's'}</>
          )}
          {result.errors.length > 0 && (
            <details style={{ marginTop: 4 }}>
              <summary style={{ cursor: 'pointer' }}>Errors</summary>
              <ul style={{ margin: 0, paddingLeft: 16 }}>
                {result.errors.map((e, i) => (
                  <li key={i}>{e.name ? `${e.name}: ` : ''}{e.reason}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
      {error && (
        <div style={{ fontSize: 11, color: '#f87171' }}>{error}</div>
      )}
    </div>
  )
}
