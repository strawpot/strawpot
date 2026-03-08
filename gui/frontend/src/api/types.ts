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
