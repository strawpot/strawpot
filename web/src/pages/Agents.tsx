import { useEffect, useState } from 'react'
import { createAgent, deleteAgent, fetchAgents, fetchRoles } from '../api'
import type { Charter } from '../types'

export default function Agents() {
  const [agents, setAgents] = useState<Charter[]>([])
  const [roleNames, setRoleNames] = useState<string[]>([])
  const [selected, setSelected] = useState<Charter | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newRole, setNewRole] = useState('')
  const [error, setError] = useState<string | null>(null)

  const load = () =>
    Promise.all([
      fetchAgents().then(setAgents),
      fetchRoles().then(rs => setRoleNames(rs.map(r => r.name))),
    ]).catch(e => setError(String(e)))

  useEffect(() => { load() }, [])

  const handleCreate = async () => {
    if (!newName.trim() || !newRole) {
      setError('Name and role are required.')
      return
    }
    try {
      await createAgent({ name: newName.trim(), role: newRole })
      setShowCreate(false)
      setNewName('')
      setNewRole('')
      load()
    } catch (e) {
      setError(String(e))
    }
  }

  const handleDelete = async (name: string) => {
    if (!confirm(`Delete agent "${name}"?`)) return
    try {
      await deleteAgent(name)
      if (selected?.name === name) setSelected(null)
      load()
    } catch (e) {
      setError(String(e))
    }
  }

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-white">Agents</h1>
        <button
          onClick={() => setShowCreate(s => !s)}
          className="text-sm bg-emerald-700 hover:bg-emerald-600 text-white px-3 py-1.5 rounded-md"
        >
          + Create
        </button>
      </div>

      {error && (
        <div className="mb-4 bg-red-950 border border-red-800 rounded-lg p-3 text-red-400 text-sm flex justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-600 hover:text-red-400">×</button>
        </div>
      )}

      {/* Create form */}
      {showCreate && (
        <div className="mb-6 bg-gray-900 border border-gray-700 rounded-lg p-4">
          <h2 className="text-sm font-medium text-gray-300 mb-3">New Agent</h2>
          <div className="flex gap-3 flex-wrap">
            <input
              type="text"
              placeholder="Agent name"
              value={newName}
              onChange={e => setNewName(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-emerald-600 w-40"
            />
            <select
              value={newRole}
              onChange={e => setNewRole(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:border-emerald-600"
            >
              <option value="">— select role —</option>
              {roleNames.map(r => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
            <button
              onClick={handleCreate}
              className="bg-emerald-700 hover:bg-emerald-600 text-white px-4 py-1.5 rounded text-sm"
            >
              Create
            </button>
            <button
              onClick={() => setShowCreate(false)}
              className="text-gray-500 hover:text-gray-300 px-2 py-1.5 text-sm"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className="flex gap-6">
        {/* Table */}
        <div className="flex-1 min-w-0">
          <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase tracking-wider">
                  <th className="text-left px-4 py-3">Name</th>
                  <th className="text-left px-4 py-3">Role</th>
                  <th className="text-left px-4 py-3">Model</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {agents.map(a => (
                  <tr
                    key={a.name}
                    onClick={() => setSelected(selected?.name === a.name ? null : a)}
                    className={`cursor-pointer transition-colors ${
                      selected?.name === a.name ? 'bg-gray-800' : 'hover:bg-gray-850'
                    }`}
                  >
                    <td className="px-4 py-3 font-mono text-emerald-400">{a.name}</td>
                    <td className="px-4 py-3 text-gray-400">{a.role}</td>
                    <td className="px-4 py-3 text-gray-400 font-mono text-xs">
                      {a.resolved_model
                        ? `${a.resolved_model.provider}/${a.resolved_model.id}`
                        : '—'}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={e => { e.stopPropagation(); handleDelete(a.name) }}
                        className="text-xs text-red-500 hover:text-red-400 px-2 py-1"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
                {agents.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-4 py-6 text-center text-gray-600">
                      No agents yet. Click <strong className="text-gray-400">+ Create</strong> to add one.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Detail panel */}
        {selected && (
          <div className="w-80 flex-shrink-0">
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
              <div className="flex items-center justify-between mb-4">
                <span className="font-mono text-emerald-400 font-medium">{selected.name}</span>
                <button onClick={() => setSelected(null)} className="text-gray-600 hover:text-gray-400 text-lg leading-none">×</button>
              </div>
              <KV label="Role" value={selected.role} />
              {selected.resolved_model && (
                <>
                  <KV label="Provider" value={selected.resolved_model.provider} />
                  <KV label="Model" value={selected.resolved_model.id} mono />
                </>
              )}
              {selected.resolved_skills && selected.resolved_skills.length > 0 && (
                <div className="mt-3">
                  <div className="text-xs text-gray-600 uppercase tracking-wider mb-1">
                    Skills ({selected.resolved_skills.length})
                  </div>
                  {selected.resolved_skills.map(s => (
                    <div key={s} className="text-xs font-mono text-gray-400">{s}</div>
                  ))}
                </div>
              )}
              {selected.resolved_tools && (
                <div className="mt-3">
                  <div className="text-xs text-gray-600 uppercase tracking-wider mb-1">Tools</div>
                  <div className="text-xs text-gray-400">
                    {selected.resolved_tools.allowed.join(', ')}
                  </div>
                </div>
              )}
              {selected.extra_skills && selected.extra_skills.length > 0 && (
                <div className="mt-3">
                  <div className="text-xs text-gray-600 uppercase tracking-wider mb-1">Extra skills</div>
                  {selected.extra_skills.map(s => (
                    <div key={s} className="text-xs font-mono text-gray-400">{s}</div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function KV({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex gap-2 text-xs mb-0.5">
      <span className="text-gray-500 w-20 flex-shrink-0">{label}</span>
      <span className={mono ? 'font-mono text-gray-300' : 'text-gray-300'}>{value}</span>
    </div>
  )
}
