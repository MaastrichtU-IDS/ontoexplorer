import { lazy, Suspense, useEffect, useState } from 'react'
import { Link, Navigate, Route, Routes, useSearchParams } from 'react-router-dom'
import NavBar from './components/NavBar'
import AuthGuard from './components/AuthGuard'
import DashboardLayout from './components/DashboardLayout'

// Route pages are code-split: each becomes its own chunk loaded on navigation,
// so the initial bundle isn't dominated by heavy pages (YASGUI on /sparql,
// recharts on the dashboard). The shell (NavBar/AuthGuard/DashboardLayout) stays
// eager so it paints immediately.
const Home = lazy(() => import('./pages/Home'))
const Search = lazy(() => import('./pages/Search'))
const Ontologies = lazy(() => import('./pages/Ontologies'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const ApiKeys = lazy(() => import('./pages/ApiKeys'))
const Webhooks = lazy(() => import('./pages/Webhooks'))
const Stats = lazy(() => import('./pages/Stats'))
const Profile = lazy(() => import('./pages/Profile'))
const OntologyPage = lazy(() => import('./pages/OntologyPage'))
const Login = lazy(() => import('./pages/Login'))
const AuthCallback = lazy(() => import('./pages/AuthCallback'))
const AdminPage = lazy(() => import('./pages/AdminPage'))
const Sparql = lazy(() => import('./pages/Sparql'))
const SparqlGallery = lazy(() => import('./pages/SparqlGallery'))

interface VersionInfo { version: string; git_ref: string | null; git_sha: string | null }

export function Footer() {
  const [ver, setVer] = useState<VersionInfo | null>(null)
  useEffect(() => {
    let alive = true
    fetch('/api/v1/version')
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (alive && d) setVer(d) })
      .catch(() => {})
    return () => { alive = false }
  }, [])

  // Prefer the build's git tag (git_ref); fall back to the packaged version.
  const label = ver ? (ver.git_ref ?? `v${ver.version}`) : null
  const sha = ver?.git_sha ?? null

  return (
    <footer style={{
      borderTop: '1px solid var(--border)',
      background: 'var(--bg-deep)',
      padding: '0.6rem 1.5rem',
      display: 'flex',
      alignItems: 'center',
      gap: '1.25rem',
    }}>
      <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>APIs</span>
      <Link
        to="/sparql"
        style={{ color: 'var(--text-dim)', fontSize: 12, textDecoration: 'none' }}
        onMouseEnter={e => (e.currentTarget.style.color = 'var(--text)')}
        onMouseLeave={e => (e.currentTarget.style.color = 'var(--text-dim)')}
      >
        SPARQL
      </Link>
      <a
        href="/api/docs"
        target="_blank"
        rel="noreferrer"
        style={{ color: 'var(--text-dim)', fontSize: 12, textDecoration: 'none' }}
        onMouseEnter={e => (e.currentTarget.style.color = 'var(--text)')}
        onMouseLeave={e => (e.currentTarget.style.color = 'var(--text-dim)')}
      >
        REST API
      </a>
      <a
        href="/mod/"
        target="_blank"
        rel="noreferrer"
        style={{ color: 'var(--text-dim)', fontSize: 12, textDecoration: 'none' }}
        onMouseEnter={e => (e.currentTarget.style.color = 'var(--text)')}
        onMouseLeave={e => (e.currentTarget.style.color = 'var(--text-dim)')}
      >
        MOD API
      </a>
      {label && (
        <span
          title={sha ? `commit ${sha}` : undefined}
          style={{ marginLeft: 'auto', color: 'var(--text-dim)', fontSize: 12, fontVariantNumeric: 'tabular-nums' }}
        >
          {label}{sha ? ` · ${sha}` : ''}
        </span>
      )}
    </footer>
  )
}

function CompareRedirect() {
  const [params] = useSearchParams()
  const next = new URLSearchParams(params)
  next.set('tab', 'compare')
  return <Navigate to={`/ontologies?${next}`} replace />
}

function PageFallback() {
  return (
    <div style={{ padding: '3rem 1.5rem', color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)' }}>
      Loading…
    </div>
  )
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ paddingTop: 'var(--nav-height)', minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <NavBar />
      {/* Suspense sits inside the shell so the nav/footer stay painted while a
          lazily-loaded page chunk resolves — only the content area shows the
          fallback. Covers the dashboard/admin group too (Shell wraps AuthGuard). */}
      <div style={{ flex: 1 }}><Suspense fallback={<PageFallback />}>{children}</Suspense></div>
      <Footer />
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Shell><Home /></Shell>} />
      <Route path="/ontologies" element={<Shell><Ontologies /></Shell>} />
      <Route path="/ontologies/:slug" element={<Shell><OntologyPage /></Shell>} />
      <Route path="/ontologies/:slug/:version" element={<Shell><OntologyPage /></Shell>} />
      <Route path="/compare" element={<CompareRedirect />} />
      <Route path="/coverage" element={<Navigate to="/ontologies?tab=coverage" replace />} />
      <Route path="/owl-profile" element={<Navigate to="/ontologies?tab=profiles" replace />} />
      <Route path="/search" element={<Shell><Search /></Shell>} />
      <Route path="/sparql" element={<Shell><Sparql /></Shell>} />
      <Route path="/sparql/gallery" element={<Shell><SparqlGallery /></Shell>} />
      <Route path="/login" element={<Shell><Login /></Shell>} />
      <Route path="/auth/:provider/callback" element={<Suspense fallback={<PageFallback />}><AuthCallback /></Suspense>} />
      <Route element={<Shell><AuthGuard /></Shell>}>
        <Route element={<DashboardLayout />}>
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/dashboard/keys" element={<ApiKeys />} />
          <Route path="/dashboard/webhooks" element={<Webhooks />} />
          <Route path="/dashboard/stats" element={<Stats />} />
          <Route path="/dashboard/profile" element={<Profile />} />
        </Route>
        <Route path="/admin" element={<AdminPage />} />
      </Route>
    </Routes>
  )
}
