import { NavLink, Outlet } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useIsMobile } from '../hooks/useIsMobile'
import { api } from '../lib/api'

const sidebarLinks = [
  { to: '/dashboard', label: 'Ontologies', end: true },
  { to: '/dashboard/keys', label: 'API Keys', end: false },
  { to: '/dashboard/webhooks', label: 'Webhooks', end: false },
  { to: '/dashboard/stats', label: 'Stats', end: false },
  { to: '/dashboard/profile', label: 'Profile', end: false },
]

// Amber pill showing how many of the caller's versions are held for review. The
// held-version inbox lives on the Ontologies page, so the badge sits on that link.
function AttentionBadge() {
  const { data } = useQuery({
    queryKey: ['attention-count'],
    queryFn: () => api.ontologies.attentionCount(),
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  })
  const n = data?.needs_review ?? 0
  if (n <= 0) return null
  return (
    <span
      role="status"
      aria-label={`${n} version${n === 1 ? '' : 's'} need your attention`}
      style={{
        marginLeft: '0.4rem',
        padding: '0.05rem 0.4rem',
        borderRadius: 999,
        fontSize: '0.7rem',
        fontWeight: 700,
        lineHeight: 1.4,
        color: 'var(--bg)',
        background: 'var(--orange)',
      }}
    >
      {n}
    </span>
  )
}

export default function DashboardLayout() {
  const isMobile = useIsMobile()

  const links = sidebarLinks.map(({ to, label, end }) => (
    <NavLink
      key={to}
      to={to}
      end={end}
      style={({ isActive }) => ({
        display: 'flex',
        alignItems: 'center',
        padding: isMobile ? '0.5rem 0.9rem' : '0.4rem 1rem',
        fontSize: 'var(--font-size-base)',
        color: isActive ? 'var(--accent)' : 'var(--text-muted)',
        background: isActive ? 'var(--bg-secondary)' : 'transparent',
        textDecoration: 'none',
        whiteSpace: 'nowrap',
        // Active marker sits on the left edge in the sidebar, the bottom edge in the tab bar.
        borderLeft: !isMobile ? (isActive ? '2px solid var(--accent)' : '2px solid transparent') : undefined,
        borderBottom: isMobile ? (isActive ? '2px solid var(--accent)' : '2px solid transparent') : undefined,
      })}
    >
      {label}
      {to === '/dashboard' && <AttentionBadge />}
    </NavLink>
  ))

  if (isMobile) {
    // Sidebar → a horizontal, scrollable tab bar pinned under the nav, so every
    // dashboard section stays reachable on a narrow screen.
    return (
      <div style={{ minHeight: 'calc(100vh - var(--nav-height))' }}>
        <nav style={{
          display: 'flex', gap: '0.25rem', overflowX: 'auto',
          borderBottom: '1px solid var(--border)',
          padding: '0 0.5rem',
        }}>
          {links}
        </nav>
        <main style={{ padding: '1.25rem 1rem', minWidth: 0 }}>
          <Outlet />
        </main>
      </div>
    )
  }

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
          {links}
        </nav>
      </aside>
      <main style={{ flex: 1, padding: '1.5rem 2rem', minWidth: 0 }}>
        <Outlet />
      </main>
    </div>
  )
}
