import { NavLink, Outlet } from 'react-router-dom'

const sidebarLinks = [
  { to: '/dashboard', label: 'Ontologies', end: true },
  { to: '/dashboard/keys', label: 'API Keys', end: false },
  { to: '/dashboard/webhooks', label: 'Webhooks', end: false },
  { to: '/dashboard/stats', label: 'Stats', end: false },
  { to: '/dashboard/profile', label: 'Profile', end: false },
]

export default function DashboardLayout() {
  return (
    <div style={{ display: 'flex', minHeight: 'calc(100vh - var(--nav-height))' }}>
      <aside style={{
        width: 140,
        borderRight: '1px solid var(--border)',
        padding: '1.5rem 0',
        flexShrink: 0,
      }}>
        <p style={{
          padding: '0 1rem',
          marginBottom: '0.75rem',
          fontSize: 'var(--font-size-sm)',
          color: 'var(--text-dim)',
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
        }}>
          Dashboard
        </p>
        <nav style={{ display: 'flex', flexDirection: 'column' }}>
          {sidebarLinks.map(({ to, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              style={({ isActive }) => ({
                padding: '0.4rem 1rem',
                fontSize: 'var(--font-size-base)',
                color: isActive ? 'var(--accent)' : 'var(--text-muted)',
                background: isActive ? 'var(--bg-secondary)' : 'transparent',
                textDecoration: 'none',
                borderLeft: isActive ? '2px solid var(--accent)' : '2px solid transparent',
              })}
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main style={{ flex: 1, padding: '1.5rem 2rem', minWidth: 0 }}>
        <Outlet />
      </main>
    </div>
  )
}
