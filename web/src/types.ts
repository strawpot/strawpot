export interface ModelConfig {
  provider: string
  id: string
  path?: string
  options?: Record<string, unknown>
}

export interface ToolsConfig {
  allowed: string[]
  bash_allowlist?: string[]
}

export interface MemoryConfig {
  layers?: string[]
  provider?: string
  max_tokens_injected?: number
}

export interface Role {
  name: string
  description?: string
  default_skills: string[]
  default_tools: ToolsConfig
  default_model: ModelConfig
  default_memory?: MemoryConfig
}

export interface Charter {
  name: string
  role: string
  model?: ModelConfig
  extra_skills?: string[]
  memory?: MemoryConfig
  tools?: ToolsConfig
  // Resolved from role defaults:
  resolved_model?: ModelConfig
  resolved_skills?: string[]
  resolved_tools?: ToolsConfig
  resolved_memory?: MemoryConfig
}

export interface ChronicleEvent {
  id: string
  ts: string
  project_id?: string
  plan_id?: string
  task_id?: string
  run_id?: string
  actor: string
  type: string
  payload: Record<string, unknown>
}

export interface ProjectConfig {
  project: {
    id: string
    name: string
    repo_path: string
    default_branch: string
  }
}
