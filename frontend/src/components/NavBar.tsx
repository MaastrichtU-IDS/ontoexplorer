import { useState } from 'react'
import { NavLink, Link } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { useRepositoryLanguages } from '../hooks/useRepositoryLanguages'
import { useIsMobile } from '../hooks/useIsMobile'
import LanguagePicker from './LanguagePicker'
import { logout } from '../lib/auth'
import ThemeToggle from './ThemeToggle'

const navLinks = [
  { to: '/ontologies',  label: 'Ontologies' },
]

// A pill-style link (Admin / Dashboard / Sign in) — same look in the desktop bar
// and the mobile menu; only the accent colour and font size differ.
function pillStyle(isActive: boolean, activeColor: string, fontSize: string): React.CSSProperties {
  return {
    color: isActive ? activeColor : 'var(--text-dim)',
    fontSize,
    border: '1px solid',
    borderColor: isActive ? activeColor : 'var(--border)',
    borderRadius: 4,
    padding: '2px 8px',
  }
}

export default function NavBar() {
  const { user, isAuthenticated } = useAuth()
  const isMobile = useIsMobile()
  const [open, setOpen] = useState(false)

  // Auth-dependent controls, shared by the desktop bar and the mobile menu.
  const authControls = (fontSize: string) =>
    isAuthenticated ? (
      <>
        {user?.is_admin && (
          <NavLink to="/admin" onClick={() => setOpen(false)}
            style={({ isActive }) => pillStyle(isActive, 'var(--orange)', fontSize)}>
            Admin
          </NavLink>
        )}
        <NavLink to="/dashboard" onClick={() => setOpen(false)}
          style={({ isActive }) => pillStyle(isActive, 'var(--od-purple)', fontSize)}>
          Dashboard
        </NavLink>
        <button onClick={() => { setOpen(false); logout() }}
          style={{ ...pillStyle(false, 'var(--od-blue)', fontSize), color: 'var(--od-blue)', borderColor: 'var(--od-blue)' }}>
          Sign out
        </button>
      </>
    ) : (
      <Link to="/login" onClick={() => setOpen(false)}
        style={{ ...pillStyle(false, 'var(--od-blue)', fontSize), color: 'var(--od-blue)', borderColor: 'var(--od-blue)' }}>
        Sign in
      </Link>
    )

  const primaryLinks = (fontSize: string, onClick?: () => void) =>
    navLinks.map(({ to, label }) => (
      <NavLink key={to} to={to} onClick={onClick}
        style={({ isActive }) => ({ color: isActive ? 'var(--text)' : 'var(--text-dim)', fontSize })}>
        {label}
      </NavLink>
    ))

  return (
    <nav style={{
      position: 'fixed', top: 0, left: 0, right: 0, zIndex: 100,
      height: 'var(--nav-height)',
      background: 'var(--bg-deep)',
      borderBottom: '1px solid var(--border)',
      display: 'flex', alignItems: 'center',
      padding: isMobile ? '0 1rem' : '0 1.5rem', gap: '1.5rem',
    }}>
      <Link to="/" onClick={() => setOpen(false)}
        style={{ color: 'var(--accent)', fontWeight: 700, fontSize: 15 }}>
        OntoExplorer
      </Link>

      {isMobile ? (
        <>
          <button
            aria-label="Menu"
            aria-expanded={open}
            onClick={() => setOpen(o => !o)}
            style={{
              marginLeft: 'auto', display: 'flex', flexDirection: 'column',
              justifyContent: 'center', gap: 4, padding: 8, color: 'var(--text)',
            }}
          >
            {[0, 1, 2].map(i => (
              <span key={i} style={{ display: 'block', width: 20, height: 2, background: 'currentColor' }} />
            ))}
          </button>
          {open && (
            <div style={{
              position: 'fixed', top: 'var(--nav-height)', left: 0, right: 0, zIndex: 100,
              background: 'var(--bg-deep)', borderBottom: '1px solid var(--border)',
              display: 'flex', flexDirection: 'column', gap: '0.9rem',
              padding: '1rem 1.25rem',
            }}>
              {primaryLinks('var(--font-size-base)', () => setOpen(false))}
              <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '0.75rem' }}>
                {authControls('var(--font-size-base)')}
              </div>
              <div style={{
                display: 'flex', alignItems: 'center', gap: '0.75rem',
                paddingTop: '0.75rem', borderTop: '1px solid var(--border)',
              }}>
                <ThemeToggle />
                <RepositoryLangPicker />
              </div>
            </div>
          )}
        </>
      ) : (
        <>
          {primaryLinks('var(--font-size-base)')}
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <ThemeToggle />
            <RepositoryLangPicker />
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              {authControls('var(--font-size-sm)')}
            </div>
          </div>
        </>
      )}
    </nav>
  )
}

function RepositoryLangPicker() {
  return <LanguagePicker languages={useRepositoryLanguages()} />
}
