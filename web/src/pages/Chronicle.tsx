import { useEffect, useState } from 'react'
import { fetchChronicle } from '../api'
import type { ChronicleEvent } from '../types'

function formatTS(ts: string) {
  return new Date(ts).toLocaleString()
}

export default function Chronicle() {
  const [events, setEvents] = useState<ChronicleEvent[]>([])
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [filterType, setFilterType] = useState('')
  const [filterActor, setFilterActor] = useState('')
  const [limit, setLimit] = useState(50)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = () => {
    setLoading(true)
    fetchChronicle({
      event_type: filterType || undefined,
      actor: filterActor || undefined,
      limit,
    })
      .then(evts => setEvents([...evts].reverse()))
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [filterType, filterActor, limit])

  const toggle = (id: string) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // Derive unique actors and types for filter dropdowns
  const allActors = [...new Set(events.map(e => e.actor))].sort()
  const allTypes = [...new Set(events.map(e => e.type))].sort()

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-white">Chronicle</h1>
        <button
          onClick={load}
          disabled={loading}
          className="text-sm text-gray-400 hover:text-white px-3 py-1.5 border border-gray-700 rounded-md"
        >
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      {error && (
        <div className="mb-4 bg-red-950 border border-red-800 rounded-lg p-3 text-red-400 text-sm flex justify-between">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-600 hover:text-red-400">×</button>
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-3 mb-6 flex-wrap">
        <select
          value={filterType}
          onChange={e => setFilterType(e.target.value)}
          className="bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:border-emerald-600"
        >
          <option value="">All types</option>
          {allTypes.map(t => <option key={t} value={t}>{t}</option>)}
        </select>

        <select
          value={filterActor}
          onChange={e => setFilterActor(e.target.value)}
          className="bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:border-emerald-600"
        >
          <option value="">All actors</option>
          {allActors.map(a => <option key={a} value={a}>{a}</option>)}
        </select>

        <select
          value={limit}
          onChange={e => setLimit(Number(e.target.value))}
          className="bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:border-emerald-600"
        >
          {[20, 50, 100, 250].map(n => (
            <option key={n} value={n}>Last {n}</option>
          ))}
        </select>

        {(filterType || filterActor) && (
          <button
            onClick={() => { setFilterType(''); setFilterActor('') }}
            className="text-sm text-gray-500 hover:text-gray-300 px-2"
          >
            Clear filters
          </button>
        )}
      </div>

      {/* Event list */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg overflow-hidden">
        {events.length === 0 ? (
          <div className="px-5 py-8 text-center text-gray-600 text-sm">
            {loading ? 'Loading…' : 'No events found.'}
          </div>
        ) : (
          <ul className="divide-y divide-gray-800">
            {events.map(e => (
              <li key={e.id} className="hover:bg-gray-850 transition-colors">
                <button
                  className="w-full text-left px-5 py-3 flex items-start gap-4"
                  onClick={() => toggle(e.id)}
                >
                  <span className="text-gray-600 font-mono text-xs w-36 flex-shrink-0 pt-0.5">
                    {formatTS(e.ts)}
                  </span>
                  <span className="text-emerald-400 font-mono text-xs flex-shrink-0 w-40 truncate">
                    {e.type}
                  </span>
                  <span className="text-gray-500 text-xs flex-shrink-0 w-28 truncate">
                    {e.actor}
                  </span>
                  <span className="text-gray-700 text-xs ml-auto">
                    {expanded.has(e.id) ? '▲' : '▼'}
                  </span>
                </button>

                {expanded.has(e.id) && (
                  <div className="px-5 pb-4">
                    <div className="text-xs text-gray-600 mb-1 font-mono">{e.id}</div>
                    <pre className="bg-gray-950 rounded p-3 text-xs text-gray-400 overflow-x-auto">
                      {JSON.stringify(e.payload, null, 2)}
                    </pre>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="mt-3 text-xs text-gray-700">
        {events.length} event{events.length !== 1 ? 's' : ''}
      </div>
    </div>
  )
}
