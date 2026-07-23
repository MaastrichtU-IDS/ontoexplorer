import { useEffect, useState } from 'react'
import { Link, Navigate, Route, Routes, useSearchParams } from 'react-router-dom'
import NavBar from './components/NavBar'
import AuthGuard from './components/AuthGuard'
import DashboardLayout from './components/DashboardLayout'
import Home from './pages/Home'
import Search from './pages/Search'
import Ontologies from './pages/Ontologies'
import Dashboard from './pages/Dashboard'
import ApiKeys from './pages/ApiKeys'
import Webhooks from './pages/Webhooks'
import Stats from './pages/Stats'
import Profile from './pages/Profile'
import OntologyPage from './pages/OntologyPage'
import Login from './pages/Login'
import AuthCallback from './pages/AuthCallback'
import AdminPage from './pages/AdminPage'
import Sparql from './pages/Sparql'
import SparqlGallery from './pages/SparqlGallery'

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
      background: '#0a0f1a',
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

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ paddingTop: 'var(--nav-height)', minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <NavBar />
      <div style={{ flex: 1 }}>{children}</div>
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
      <Route path="/auth/:provider/callback" element={<AuthCallback />} />
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
