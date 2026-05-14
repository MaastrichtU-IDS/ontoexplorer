import { NavLink, Link } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { logout } from '../lib/auth'

const navLinks = [
  { to: '/ontologies', label: 'Ontologies' },
  { to: '/dashboard', label: 'Dashboard' },
]

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
      <div style={{ marginLeft: 'auto' }}>
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
            <span style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)' }}>
              {user?.display_name}
            </span>
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
