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
  user_task: string | null;
  summary: string | null;
  conversation_id: number | null;
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
  interactive: boolean;
  agents: Record<string, AgentInfo>;
  events: TraceEvent[];
  tree: TreeData;
}

export interface AskUserPending {
  request_id: string;
  question: string;
  choices: string[] | null;
  default_value: string | null;
  why: string | null;
  response_format: string | null;
  timestamp: number;
}

export interface ChatMessage {
  id: string;
  role: "agent" | "user";
  text: string;
  timestamp: number;
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
  config_count: number;
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

export interface AgentValidation {
  tools_ok: boolean;
  missing_tools: { name: string; install_hint: string | null }[];
  env_ok: boolean;
  missing_env: string[];
  setup_command: string | null;
  setup_description: string | null;
}

export interface DailyStats {
  date: string;
  total: number;
  completed: number;
  failed: number;
  avg_duration_ms: number | null;
}

export interface ProjectStats {
  period: string;
  since: string;
  until: string;
  total_runs: number;
  completed: number;
  failed: number;
  success_rate: number;
  avg_duration_ms: number | null;
  daily: DailyStats[];
}

export interface ConversationSession {
  run_id: string;
  task: string | null;
  user_task: string | null;
  summary: string | null;
  status: string;
  exit_code: number | null;
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
  role: string;
  interactive?: boolean;
  chat_messages?: ChatMessage[];
}

export interface Conversation {
  id: number;
  project_id: number;
  title: string | null;
  created_at: string;
  updated_at: string | null;
  pending_task: string | null;
  sessions: ConversationSession[];
  has_more: boolean;
}

export interface ConversationListItem {
  id: number;
  project_id: number;
  title: string | null;
  created_at: string;
  updated_at: string | null;
  session_count: number;
  last_activity: string | null;
}

export interface RecentConversation extends ConversationListItem {
  project_name: string;
}

export interface ConversationList {
  items: ConversationListItem[];
  total: number;
  page: number;
  per_page: number;
}

export interface ImuConversation {
  id: number;
  title: string | null;
  created_at: string;
  updated_at: string | null;
  session_count: number;
  active_session_count: number;
}

export interface Schedule {
  id: number;
  name: string;
  project_id: number;
  project_name: string;
  role: string | null;
  task: string;
  cron_expr: string;
  enabled: boolean;
  system_prompt: string | null;
  skip_if_running: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  last_error: string | null;
  created_at: string;
}
