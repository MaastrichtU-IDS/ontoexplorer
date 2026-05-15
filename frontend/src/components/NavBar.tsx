import { useState } from 'react'
import { NavLink, Link } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { useLang } from '../hooks/useLang'
import { logout } from '../lib/auth'

const navLinks = [
  { to: '/ontologies', label: 'Ontologies' },
]

function LangPicker() {
  const { sessionLang, setSessionLang } = useLang()
  const [open, setOpen] = useState(false)

  const COMMON = [
    { tag: null as string | null, label: 'All languages' },
    { tag: 'en', label: 'English' },
    { tag: 'fr', label: 'French' },
    { tag: 'de', label: 'German' },
    { tag: 'nl', label: 'Dutch' },
    { tag: 'es', label: 'Spanish' },
    { tag: 'ja', label: 'Japanese' },
    { tag: 'zh', label: 'Chinese' },
  ]

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
          borderRadius: 'var(--radius)', minWidth: 140, boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
        }}>
          {COMMON.map(({ tag, label }) => (
            <button
              key={tag ?? '_all'}
              onClick={() => { setSessionLang(tag); setOpen(false) }}
              style={{
                display: 'block', width: '100%', textAlign: 'left',
                padding: '6px 12px', background: 'none', border: 'none',
                color: sessionLang === tag ? 'var(--accent)' : 'var(--text)',
                fontSize: 12, cursor: 'pointer',
              }}
            >
              {label}
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
