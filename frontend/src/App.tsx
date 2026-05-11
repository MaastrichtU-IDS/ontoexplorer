import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import ApiKeys from './pages/ApiKeys'
import Dashboard from './pages/Dashboard'
import Stats from './pages/Stats'
import Webhooks from './pages/Webhooks'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/app/dashboard" element={<Dashboard />} />
        <Route path="/app/dashboard/keys" element={<ApiKeys />} />
        <Route path="/app/dashboard/webhooks" element={<Webhooks />} />
        <Route path="/app/dashboard/stats" element={<Stats />} />
        <Route path="/" element={<Dashboard />} />
      </Route>
    </Routes>
  )
}
