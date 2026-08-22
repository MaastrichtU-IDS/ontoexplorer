import { NavLink, Link } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { useRepositoryLanguages } from '../hooks/useRepositoryLanguages'
import LanguagePicker from './LanguagePicker'
import { logout } from '../lib/auth'
import ThemeToggle from './ThemeToggle'

const navLinks = [
  { to: '/ontologies',  label: 'Ontologies' },
]


export default function NavBar() {
  const { user, isAuthenticated } = useAuth()

  return (
    <nav style={{
      position: 'fixed', top: 0, left: 0, right: 0, zIndex: 100,
      height: 'var(--nav-height)',
      background: 'var(--bg-deep)',
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
        <ThemeToggle />
        <RepositoryLangPicker />
        {isAuthenticated ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            {user?.is_admin && (
              <NavLink
                to="/admin"
                style={({ isActive }) => ({
                  color: isActive ? 'var(--orange)' : 'var(--text-dim)',
                  fontSize: 'var(--font-size-sm)',
                  border: '1px solid',
                  borderColor: isActive ? 'var(--orange)' : 'var(--border)',
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
                color: isActive ? 'var(--od-purple)' : 'var(--text-dim)',
                fontSize: 'var(--font-size-sm)',
                border: '1px solid',
                borderColor: isActive ? 'var(--od-purple)' : 'var(--border)',
                borderRadius: 4,
                padding: '2px 8px',
              })}
            >
              Dashboard
            </NavLink>
            <button
              onClick={() => logout()}
              style={{
                color: 'var(--od-blue)',
                fontSize: 'var(--font-size-sm)',
                border: '1px solid var(--od-blue)',
                borderRadius: 4,
                padding: '2px 8px',
              }}
            >
              Sign out
            </button>
          </div>
        ) : (
          <Link
            to="/login"
            style={{
              color: 'var(--od-blue)',
              fontSize: 'var(--font-size-sm)',
              border: '1px solid var(--od-blue)',
              borderRadius: 4,
              padding: '2px 8px',
            }}
          >
            Sign in
          </Link>
        )}
      </div>
    </nav>
  )
}

function RepositoryLangPicker() {
  return <LanguagePicker languages={useRepositoryLanguages()} />
}
