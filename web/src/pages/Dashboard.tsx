import { useEffect, useState } from 'react'
import { fetchAgents, fetchChronicle, fetchProject, fetchRoles } from '../api'
import type { ChronicleEvent, ProjectConfig } from '../types'

function formatTS(ts: string) {
  return new Date(ts).toLocaleString()
}

export default function Dashboard() {
  const [project, setProject] = useState<ProjectConfig | null>(null)
  const [roleCnt, setRoleCnt] = useState(0)
  const [agentCnt, setAgentCnt] = useState(0)
  const [events, setEvents] = useState<ChronicleEvent[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([
      fetchProject().then(setProject),
      fetchRoles().then(r => setRoleCnt(r.length)),
      fetchAgents().then(a => setAgentCnt(a.length)),
      fetchChronicle({ limit: 10 }).then(evts =>
        setEvents([...evts].reverse().slice(0, 10)),
      ),
    ]).catch(e => setError(String(e)))
  }, [])

  if (error) return <ErrorBox msg={error} />

  return (
    <div className="p-8 max-w-4xl">
      <h1 className="text-xl font-semibold text-white mb-6">Dashboard</h1>

      {/* Project card */}
      {project && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-5 mb-6">
          <div className="text-lg font-medium text-white mb-3">
            {project.project.name}
          </div>
          <div className="grid grid-cols-2 gap-y-2 text-sm">
            <span className="text-gray-500">ID</span>
            <span className="text-gray-300 font-mono">{project.project.id}</span>
            <span className="text-gray-500">Path</span>
            <span className="text-gray-300 font-mono">{project.project.repo_path}</span>
            <span className="text-gray-500">Branch</span>
            <span className="text-gray-300">{project.project.default_branch}</span>
          </div>
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        {[
          { label: 'Roles', value: roleCnt, link: '/roles' },
          { label: 'Agents', value: agentCnt, link: '/agents' },
          { label: 'Chronicle Events', value: events.length > 0 ? '…' : '0', link: '/chronicle' },
        ].map(({ label, value }) => (
          <div key={label} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
            <div className="text-2xl font-bold text-white">{value}</div>
            <div className="text-sm text-gray-500 mt-1">{label}</div>
          </div>
        ))}
      </div>

      {/* Recent events */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg">
        <div className="px-5 py-3 border-b border-gray-800 text-sm font-medium text-gray-400">
          Recent Events
        </div>
        {events.length === 0 ? (
          <div className="px-5 py-4 text-sm text-gray-600">No events yet.</div>
        ) : (
          <ul className="divide-y divide-gray-800">
            {events.map(e => (
              <li key={e.id} className="px-5 py-3 flex items-center gap-4 text-sm">
                <span className="text-gray-600 font-mono text-xs w-36 flex-shrink-0">
                  {formatTS(e.ts)}
                </span>
                <span className="text-emerald-400 font-mono text-xs">{e.type}</span>
                <span className="text-gray-500 text-xs">{e.actor}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

function ErrorBox({ msg }: { msg: string }) {
  return (
    <div className="p-8">
      <div className="bg-red-950 border border-red-800 rounded-lg p-4 text-red-400 text-sm">
        {msg}
      </div>
    </div>
  )
}
