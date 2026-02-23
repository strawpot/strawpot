import { useEffect, useState } from 'react'
import { deleteRole, fetchRoles } from '../api'
import type { Role } from '../types'

export default function Roles() {
  const [roles, setRoles] = useState<Role[]>([])
  const [selected, setSelected] = useState<Role | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = () =>
    fetchRoles()
      .then(setRoles)
      .catch(e => setError(String(e)))

  useEffect(() => { load() }, [])

  const handleDelete = async (name: string) => {
    if (!confirm(`Delete role "${name}"?`)) return
    try {
      await deleteRole(name)
      if (selected?.name === name) setSelected(null)
      load()
    } catch (e) {
      setError(String(e))
    }
  }

  if (error) return <ErrorBox msg={error} onDismiss={() => setError(null)} />

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-white">Roles</h1>
        <span className="text-sm text-gray-500">{roles.length} roles</span>
      </div>

      <div className="flex gap-6">
        {/* Table */}
        <div className="flex-1 min-w-0">
          <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800 text-gray-500 text-xs uppercase tracking-wider">
                  <th className="text-left px-4 py-3">Name</th>
                  <th className="text-left px-4 py-3">Description</th>
                  <th className="text-left px-4 py-3">Model</th>
                  <th className="text-left px-4 py-3">Skills</th>
                  <th className="text-left px-4 py-3">Tools</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800">
                {roles.map(r => (
                  <tr
                    key={r.name}
                    onClick={() => setSelected(selected?.name === r.name ? null : r)}
                    className={`cursor-pointer transition-colors ${
                      selected?.name === r.name
                        ? 'bg-gray-800'
                        : 'hover:bg-gray-850'
                    }`}
                  >
                    <td className="px-4 py-3 font-mono text-emerald-400">{r.name}</td>
                    <td className="px-4 py-3 text-gray-400 max-w-xs truncate">
                      {r.description ?? '—'}
                    </td>
                    <td className="px-4 py-3 text-gray-400 font-mono text-xs">
                      {r.default_model.provider}/{r.default_model.id}
                    </td>
                    <td className="px-4 py-3 text-gray-400">{r.default_skills.length}</td>
                    <td className="px-4 py-3 text-gray-400 text-xs">
                      {r.default_tools.allowed.join(', ')}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={e => { e.stopPropagation(); handleDelete(r.name) }}
                        className="text-xs text-red-500 hover:text-red-400 px-2 py-1"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
                {roles.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-6 text-center text-gray-600">
                      No roles found. Run <code className="font-mono">lt init</code> first.
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
                <button
                  onClick={() => setSelected(null)}
                  className="text-gray-600 hover:text-gray-400 text-lg leading-none"
                >
                  ×
                </button>
              </div>
              <Section title="Model">
                <KV label="Provider" value={selected.default_model.provider} />
                <KV label="ID" value={selected.default_model.id} mono />
              </Section>
              <Section title="Tools">
                <KV label="Allowed" value={selected.default_tools.allowed.join(', ')} />
                {selected.default_tools.bash_allowlist && (
                  <div className="mt-1">
                    <div className="text-xs text-gray-600 mb-1">Bash allowlist</div>
                    {selected.default_tools.bash_allowlist.map(p => (
                      <div key={p} className="text-xs font-mono text-gray-400">{p}</div>
                    ))}
                  </div>
                )}
              </Section>
              <Section title={`Skills (${selected.default_skills.length})`}>
                {selected.default_skills.map(s => (
                  <div key={s} className="text-xs font-mono text-gray-400">{s}</div>
                ))}
                {selected.default_skills.length === 0 && (
                  <div className="text-xs text-gray-600">None</div>
                )}
              </Section>
              {selected.default_memory && (
                <Section title="Memory">
                  <KV label="Provider" value={selected.default_memory.provider ?? '—'} />
                  <KV
                    label="Max tokens"
                    value={String(selected.default_memory.max_tokens_injected ?? '—')}
                  />
                  <KV
                    label="Layers"
                    value={(selected.default_memory.layers ?? []).join(', ')}
                  />
                </Section>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <div className="text-xs text-gray-600 uppercase tracking-wider mb-1">{title}</div>
      {children}
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

function ErrorBox({ msg, onDismiss }: { msg: string; onDismiss: () => void }) {
  return (
    <div className="p-8">
      <div className="bg-red-950 border border-red-800 rounded-lg p-4 text-red-400 text-sm flex items-start justify-between">
        <span>{msg}</span>
        <button onClick={onDismiss} className="ml-4 text-red-600 hover:text-red-400">×</button>
      </div>
    </div>
  )
}
