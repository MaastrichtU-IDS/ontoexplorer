import { useState } from 'react'
import { NavLink, Link } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { useLang } from '../hooks/useLang'
import { useRepositoryLanguages } from '../hooks/useRepositoryLanguages'
import { logout } from '../lib/auth'

const navLinks = [
  { to: '/ontologies', label: 'Ontologies' },
]

const LANG_NAMES: Record<string, string> = {
  en: 'English', fr: 'French', de: 'German', nl: 'Dutch', es: 'Spanish',
  it: 'Italian', pt: 'Portuguese', ru: 'Russian', zh: 'Chinese', ja: 'Japanese',
  ko: 'Korean', ar: 'Arabic', pl: 'Polish', sv: 'Swedish', da: 'Danish',
  fi: 'Finnish', no: 'Norwegian', cs: 'Czech', hu: 'Hungarian', ro: 'Romanian',
}

function LangPicker() {
  const { sessionLang, setSessionLang } = useLang()
  const repoLangs = useRepositoryLanguages()
  const [open, setOpen] = useState(false)

  return (
    <div style={{ position: 'relative' }}>
      <button
        onClick={() => setOpen(v => !v)}
        style={{
          background: 'none', border: '1px solid var(--border)',
          borderRadius: 'var(--radius)', padding: '4px 10px',
          color: 'var(--text-dim)', fontSize: 12, cursor: 'pointer',
        }}
      >
        {'🌐'} {sessionLang ?? 'All'}
      </button>
      {open && (
        <div style={{
          position: 'absolute', right: 0, top: '110%', zIndex: 100,
          background: 'var(--bg-secondary)', border: '1px solid var(--border)',
          borderRadius: 'var(--radius)', minWidth: 160, boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
          maxHeight: 320, overflowY: 'auto',
        }}>
          <button
            onClick={() => { setSessionLang(null); setOpen(false) }}
            style={{
              display: 'block', width: '100%', textAlign: 'left',
              padding: '6px 12px', background: 'none', border: 'none',
              color: sessionLang === null ? 'var(--accent)' : 'var(--text)',
              fontSize: 12, cursor: 'pointer',
            }}
          >
            All languages
          </button>
          {repoLangs.map(({ lang }) => (
            <button
              key={lang}
              onClick={() => { setSessionLang(lang || null); setOpen(false) }}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                width: '100%', textAlign: 'left',
                padding: '6px 12px', background: 'none', border: 'none',
                color: sessionLang === (lang ? lang : null) ? 'var(--accent)' : 'var(--text)',
                fontSize: 12, cursor: 'pointer', gap: 8,
              }}
            >
              <span>{LANG_NAMES[lang] ?? (lang || 'untagged')}</span>
              <span style={{ fontSize: 10, color: 'var(--text-dim)', flexShrink: 0 }}>{lang || '—'}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export default function NavBar() {
  const { user, isAuthenticated } = useAuth()

  return (
    <nav style={{
      position: 'fixed', top: 0, left: 0, right: 0, zIndex: 100,
      height: 'var(--nav-height)',
      background: '#0a0f1a',
      borderBottom: '1px solid var(--border)',
      display: 'flex', alignItems: 'center',
      padding: '0 1.5rem', gap: '1.5rem',
    }}>
      <Link to="/" style={{ color: 'var(--accent)', fontWeight: 700, fontSize: 15 }}>
        OntoExplorer
      </Link>
      {navLinks.map(({ to, label }) => (
        <NavLink
          key={to}
          to={to}
          style={({ isActive }) => ({
            color: isActive ? 'var(--text)' : 'var(--text-dim)',
            fontSize: 'var(--font-size-base)',
          })}
        >
          {label}
        </NavLink>
      ))}
      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
        <LangPicker />
        {isAuthenticated ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            {user?.is_admin && (
              <NavLink
                to="/admin"
                style={({ isActive }) => ({
                  color: isActive ? '#f0883e' : 'var(--text-dim)',
                  fontSize: 'var(--font-size-sm)',
                  border: '1px solid',
                  borderColor: isActive ? '#f0883e' : 'var(--border)',
                  borderRadius: 4,
                  padding: '2px 8px',
                })}
              >
                Admin
              </NavLink>
            )}
            <NavLink
              to="/dashboard"
              style={({ isActive }) => ({
                color: isActive ? 'var(--text)' : 'var(--text-dim)',
                fontSize: 'var(--font-size-sm)',
              })}
            >
              Dashboard
            </NavLink>
            <button
              onClick={() => logout()}
              style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}
            >
              Sign out
            </button>
          </div>
        ) : (
          <Link to="/login" style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)' }}>
            Sign in
          </Link>
        )}
      </div>
    </nav>
  )
}
