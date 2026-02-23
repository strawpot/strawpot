import type { Charter, ChronicleEvent, ProjectConfig, Role } from './types'

const BASE = '/api'

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: res.statusText }))
    throw new Error(err.error ?? res.statusText)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

// Project
export const fetchProject = () => req<ProjectConfig>('GET', '/project')

// Roles
export const fetchRoles = () => req<Role[]>('GET', '/roles')
export const fetchRole = (name: string) => req<Role>('GET', `/roles/${name}`)
export const createRole = (role: Partial<Role>) => req<Role>('POST', '/roles', role)
export const deleteRole = (name: string) => req<void>('DELETE', `/roles/${name}`)

// Agents
export const fetchAgents = () => req<Charter[]>('GET', '/agents')
export const fetchAgent = (name: string) => req<Charter>('GET', `/agents/${name}`)
export const createAgent = (data: { name: string; role: string }) =>
  req<Charter>('POST', '/agents', data)
export const deleteAgent = (name: string) => req<void>('DELETE', `/agents/${name}`)

// Chronicle
export interface ChronicleFilter {
  event_type?: string
  actor?: string
  limit?: number
}
export const fetchChronicle = (filter: ChronicleFilter = {}) => {
  const params = new URLSearchParams()
  if (filter.event_type) params.set('event_type', filter.event_type)
  if (filter.actor) params.set('actor', filter.actor)
  if (filter.limit) params.set('limit', String(filter.limit))
  const qs = params.toString()
  return req<ChronicleEvent[]>('GET', `/chronicle${qs ? '?' + qs : ''}`)
}
