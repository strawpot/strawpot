import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Roles from './pages/Roles'
import Agents from './pages/Agents'
import Chronicle from './pages/Chronicle'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="roles" element={<Roles />} />
          <Route path="agents" element={<Agents />} />
          <Route path="chronicle" element={<Chronicle />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
