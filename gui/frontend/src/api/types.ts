export interface Project {
  id: number;
  display_name: string;
  working_dir: string;
  created_at: string;
  dir_exists: boolean;
}

export interface Session {
  run_id: string;
  project_id: number;
  role: string;
  runtime: string;
  isolation: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
  exit_code: number | null;
  task: string | null;
  summary: string | null;
}

export interface SessionList {
  items: Session[];
  total: number;
  page: number;
  per_page: number;
}

export interface AgentInfo {
  role: string;
  runtime: string;
  parent: string | null;
  started_at: string;
  pid: number | null;
}

export interface TraceEvent {
  ts: string;
  event: string;
  trace_id: string;
  span_id: string;
  parent_span: string | null;
  data: Record<string, unknown>;
}

export interface SessionDetail extends Session {
  agents: Record<string, AgentInfo>;
  events: TraceEvent[];
}

export interface TreeNode {
  agent_id: string;
  role: string;
  runtime: string;
  status: "running" | "completed" | "failed";
  exit_code: number | null;
  started_at: string | null;
  duration_ms: number | null;
  parent: string | null;
}

export interface PendingDelegation {
  role: string;
  requested_by: string | null;
  span_id: string;
}

export interface DeniedDelegation {
  role: string;
  reason: string;
  span_id: string;
}

export interface TreeData {
  nodes: TreeNode[];
  pending_delegations: PendingDelegation[];
  denied_delegations: DeniedDelegation[];
}

export interface ProjectFile {
  name: string;
  path: string;
  size: number;
  modified_at: string;
}

export interface Resource {
  name: string;
  version: string | null;
  description: string;
  source: "global" | "project";
  path: string;
}

export interface ResourceDetail extends Resource {
  frontmatter: Record<string, unknown>;
  body: string;
}

export interface ProjectResource extends Resource {
  type: string; // "roles" | "skills" | "agents" | "memories"
}

export interface InstallResult {
  exit_code: number;
  stdout: string;
  stderr: string;
}

export interface EnvVarSchema {
  required?: boolean;
  description?: string;
}

export interface ParamSchema {
  type?: string;
  default?: unknown;
  description?: string;
}

export interface ResourceConfig {
  env_schema: Record<string, EnvVarSchema>;
  env_values: Record<string, string>;
  params_schema: Record<string, ParamSchema>;
  params_values: Record<string, unknown>;
}
