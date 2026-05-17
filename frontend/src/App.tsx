import { Route, Routes } from 'react-router-dom'
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

function Footer() {
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
      <a
        href="/sparql"
        style={{ color: 'var(--text-dim)', fontSize: 12, textDecoration: 'none' }}
        onMouseEnter={e => (e.currentTarget.style.color = 'var(--text)')}
        onMouseLeave={e => (e.currentTarget.style.color = 'var(--text-dim)')}
      >
        SPARQL
      </a>
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
    </footer>
  )
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
