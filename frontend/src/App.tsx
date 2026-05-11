import { Route, Routes } from 'react-router-dom'
import NavBar from './components/NavBar'
import AuthGuard from './components/AuthGuard'
import Home from './pages/Home'
import Browse from './pages/Browse'
import TermPage from './pages/TermPage'
import Search from './pages/Search'
import Dashboard from './pages/Dashboard'
import ApiKeys from './pages/ApiKeys'
import Webhooks from './pages/Webhooks'
import Stats from './pages/Stats'
import Login from './pages/Login'
import AuthCallback from './pages/AuthCallback'

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ paddingTop: 'var(--nav-height)', minHeight: '100vh' }}>
      <NavBar />
      {children}
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Shell><Home /></Shell>} />
      <Route path="/browse" element={<Shell><Browse /></Shell>} />
      <Route path="/browse/:oid/:vid" element={<Shell><Browse /></Shell>} />
      <Route path="/browse/:oid/:vid/term/*" element={<Shell><TermPage /></Shell>} />
      <Route path="/search" element={<Shell><Search /></Shell>} />
      <Route path="/login" element={<Shell><Login /></Shell>} />
      <Route path="/auth/:provider/callback" element={<AuthCallback />} />
      <Route element={<Shell><AuthGuard /></Shell>}>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/dashboard/keys" element={<ApiKeys />} />
        <Route path="/dashboard/webhooks" element={<Webhooks />} />
        <Route path="/dashboard/stats" element={<Stats />} />
      </Route>
    </Routes>
  )
}
