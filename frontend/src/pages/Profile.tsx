import { useState, useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../hooks/useAuth'
import { api } from '../lib/api'
import { linkProvider } from '../lib/auth'

const PROVIDER_LABELS: Record<string, string> = {
  github: 'GitHub',
  google: 'Google',
  orcid: 'ORCID',
}

// Providers offered for linking — mirror the enabled providers on the Login page
// (Google is disabled for now; the backend still supports it if re-enabled there).
const LINKABLE_PROVIDERS = ['orcid', 'github'] as const

export default function Profile() {
  const { user } = useAuth()
  const queryClient = useQueryClient()

  const [langPrefs, setLangPrefs] = useState({ preferred_lang: '', lang_fallback_strategy: 'silent' })
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState<string | null>(null)

  const [linkMsg, setLinkMsg] = useState<{ text: string; ok: boolean } | null>(null)
  const [busyProvider, setBusyProvider] = useState<string | null>(null)

  useEffect(() => {
    if (user) {
      setLangPrefs({
        preferred_lang: user.preferred_lang ?? '',
        lang_fallback_strategy: user.lang_fallback_strategy ?? 'silent',
      })
    }
  }, [user?.preferred_lang, user?.lang_fallback_strategy])

  // Surface the result of a link round-trip (/callback redirects here with
  // ?linked=<provider> or ?link_error=<message>), then clean the URL.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const linked = params.get('linked')
    const err = params.get('link_error')
    if (linked) setLinkMsg({ text: `Connected ${PROVIDER_LABELS[linked] || linked}.`, ok: true })
    else if (err) setLinkMsg({ text: err, ok: false })
    if (linked || err) {
      window.history.replaceState({}, '', window.location.pathname)
      queryClient.invalidateQueries({ queryKey: ['auth', 'me'] })
    }
  }, [])

  async function connectProvider(provider: (typeof LINKABLE_PROVIDERS)[number]) {
    setLinkMsg(null)
    setBusyProvider(provider)
    try {
      await linkProvider(provider)  // navigates away on success
    } catch {
      setLinkMsg({ text: `Could not start linking ${PROVIDER_LABELS[provider]}.`, ok: false })
      setBusyProvider(null)
    }
  }

  async function disconnectProvider(provider: (typeof LINKABLE_PROVIDERS)[number]) {
    setLinkMsg(null)
    setBusyProvider(provider)
    try {
      await api.auth.unlink(provider)
      await queryClient.invalidateQueries({ queryKey: ['auth', 'me'] })
      setLinkMsg({ text: `Disconnected ${PROVIDER_LABELS[provider]}.`, ok: true })
    } catch (e) {
      setLinkMsg({ text: (e as Error)?.message || `Could not disconnect ${PROVIDER_LABELS[provider]}.`, ok: false })
    } finally {
      setBusyProvider(null)
    }
  }

  if (!user) return <p style={{ color: 'var(--text-dim)' }}>Loading…</p>

  const memberSince = new Date(user.created_at).toLocaleDateString('en-US', {
    year: 'numeric', month: 'long', day: 'numeric',
  })

  async function saveLangPrefs() {
    setSaving(true)
    setSaveMsg(null)
    try {
      await api.auth.patchMe({
        preferred_lang: langPrefs.preferred_lang || null,
        lang_fallback_strategy: langPrefs.lang_fallback_strategy,
      })
      await queryClient.invalidateQueries({ queryKey: ['auth', 'me'] })
      setSaveMsg('Saved')
    } catch {
      setSaveMsg('Error saving')
    } finally {
      setSaving(false)
      setTimeout(() => setSaveMsg(null), 3000)
    }
  }

  return (
    <div style={{ maxWidth: 480 }}>
      <h1 style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: '1.5rem' }}>Profile</h1>

      <div style={{
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        overflow: 'hidden',
      }}>
        <div style={{ padding: '1.25rem 1.5rem', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <div style={{
            width: 48, height: 48, borderRadius: '50%',
            background: 'var(--accent)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '1.25rem', fontWeight: 700, color: '#0a0f1a',
            flexShrink: 0,
          }}>
            {(user.display_name || user.email || '?')[0].toUpperCase()}
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
              <span style={{ fontWeight: 600, fontSize: '1rem', color: 'var(--text)' }}>
                {user.display_name || '(no name)'}
              </span>
              {user.is_admin && (
                <span style={{
                  fontSize: '0.7rem', fontWeight: 700,
                  background: '#f0883e22', color: '#f0883e',
                  border: '1px solid #f0883e66',
                  borderRadius: 3, padding: '1px 6px',
                  letterSpacing: '0.05em', textTransform: 'uppercase',
                }}>
                  Admin
                </span>
              )}
            </div>
            <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)', marginTop: 2 }}>
              {user.email || '—'}
            </div>
          </div>
        </div>

        <div style={{ padding: '1rem 1.5rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          <Row label="Member since" value={memberSince} />
        </div>
      </div>

      {/* Connected accounts section */}
      <div style={{
        marginTop: '1.5rem',
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        padding: '1.25rem 1.5rem',
      }}>
        <h2 style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text)', marginBottom: '0.25rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Connected accounts
        </h2>
        <p style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)', marginBottom: '1rem' }}>
          Sign in with any linked provider. You can't remove your only one.
        </p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {LINKABLE_PROVIDERS.map(provider => {
            const connected = (user.connected_providers || []).includes(provider)
            const isOnly = connected && (user.connected_providers || []).length <= 1
            const busy = busyProvider === provider
            return (
              <div key={provider} style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '8px 12px', borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--border)', background: 'var(--bg)',
              }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 'var(--font-size-sm)', color: 'var(--text)' }}>
                  {PROVIDER_LABELS[provider]}
                  {connected && (
                    <span style={{ fontSize: '0.7rem', color: '#3fb950' }}>● connected</span>
                  )}
                </span>
                {connected ? (
                  <button
                    onClick={() => disconnectProvider(provider)}
                    disabled={busy || isOnly}
                    title={isOnly ? "Can't remove your only sign-in method" : undefined}
                    style={{
                      padding: '4px 12px', borderRadius: 'var(--radius-sm)',
                      background: 'transparent', border: '1px solid var(--border)',
                      color: isOnly ? 'var(--text-dim)' : 'var(--error, #e06c75)',
                      fontSize: 'var(--font-size-sm)',
                      cursor: (busy || isOnly) ? 'default' : 'pointer', opacity: (busy || isOnly) ? 0.6 : 1,
                    }}
                  >
                    {busy ? '…' : 'Disconnect'}
                  </button>
                ) : (
                  <button
                    onClick={() => connectProvider(provider)}
                    disabled={busy}
                    style={{
                      padding: '4px 12px', borderRadius: 'var(--radius-sm)',
                      background: 'var(--accent)', border: 'none',
                      color: '#0a0f1a', fontSize: 'var(--font-size-sm)', fontWeight: 600,
                      cursor: busy ? 'default' : 'pointer', opacity: busy ? 0.7 : 1,
                    }}
                  >
                    {busy ? '…' : 'Connect'}
                  </button>
                )}
              </div>
            )
          })}
        </div>

        {linkMsg && (
          <p style={{ marginTop: '0.75rem', fontSize: 'var(--font-size-sm)', color: linkMsg.ok ? '#3fb950' : 'var(--error, #e06c75)' }}>
            {linkMsg.text}
          </p>
        )}
      </div>

      {/* Language preferences section */}
      <div style={{
        marginTop: '1.5rem',
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        padding: '1.25rem 1.5rem',
      }}>
        <h2 style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text)', marginBottom: '1rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Language
        </h2>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <label style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)' }}>
            Preferred language (BCP-47, e.g. en, fr, de, nl)
            <input
              type="text"
              value={langPrefs.preferred_lang}
              onChange={e => setLangPrefs(p => ({ ...p, preferred_lang: e.target.value }))}
              placeholder="en"
              style={{
                display: 'block', marginTop: 6,
                background: 'var(--bg)', border: '1px solid var(--border)',
                borderRadius: 'var(--radius-sm)', padding: '6px 10px',
                color: 'var(--text)', fontSize: 'var(--font-size-sm)', width: 160,
                outline: 'none',
              }}
            />
          </label>

          <div>
            <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)', marginBottom: 8 }}>
              When preferred language has no label
            </div>
            {([
              { value: 'silent',           label: 'Use best available silently' },
              { value: 'show_all',         label: 'Show all language variants' },
              { value: 'indicate_missing', label: 'Indicate missing label' },
            ] as const).map(opt => (
              <label key={opt.value} style={{
                display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6,
                fontSize: 'var(--font-size-sm)', color: 'var(--text)', cursor: 'pointer',
              }}>
                <input
                  type="radio"
                  name="lang_fallback_strategy"
                  value={opt.value}
                  checked={langPrefs.lang_fallback_strategy === opt.value}
                  onChange={() => setLangPrefs(p => ({ ...p, lang_fallback_strategy: opt.value }))}
                />
                {opt.label}
              </label>
            ))}
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <button
              onClick={saveLangPrefs}
              disabled={saving}
              style={{
                padding: '6px 16px', borderRadius: 'var(--radius-sm)',
                background: 'var(--accent)', border: 'none',
                color: '#0a0f1a', fontSize: 'var(--font-size-sm)', fontWeight: 600,
                cursor: saving ? 'default' : 'pointer', opacity: saving ? 0.7 : 1,
              }}
            >
              {saving ? 'Saving…' : 'Save language settings'}
            </button>
            {saveMsg && (
              <span style={{ fontSize: 'var(--font-size-sm)', color: saveMsg === 'Saved' ? '#3fb950' : 'var(--error, #e06c75)' }}>
                {saveMsg}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem' }}>
      <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text-dim)', flexShrink: 0 }}>{label}</span>
      <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--text)', textAlign: 'right' }}>{value}</span>
    </div>
  )
}
