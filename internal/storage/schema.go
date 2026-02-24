package storage

const SchemaVersion = 5

// migrateV2SQL adds embedding and content columns to skill_files and memory_chunks.
const migrateV2SQL = `
ALTER TABLE skill_files   ADD COLUMN embedding     BLOB;
ALTER TABLE skill_files   ADD COLUMN content_hash  TEXT;
ALTER TABLE memory_chunks ADD COLUMN embedding     BLOB;
ALTER TABLE memory_chunks ADD COLUMN content       TEXT;
`

// migrateV3SQL adds content and scope columns to skill_files.
// scope: "global" = ~/.loguetown/skills/global/, "project" = .loguetown/skills/
const migrateV3SQL = `
ALTER TABLE skill_files ADD COLUMN content TEXT;
ALTER TABLE skill_files ADD COLUMN scope   TEXT NOT NULL DEFAULT 'project';
`

// migrateV4SQL adds agent_name to skill_files to support agent-scoped skills.
// scope: "agent" = .loguetown/skills/agents/<agent-name>/
const migrateV4SQL = `
ALTER TABLE skill_files ADD COLUMN agent_name TEXT;
`

const createTablesSQL = `
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS projects (
  id             TEXT PRIMARY KEY,
  name           TEXT NOT NULL,
  repo_path      TEXT NOT NULL,
  default_branch TEXT NOT NULL DEFAULT 'main',
  config_json    TEXT,
  created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
  id                    TEXT PRIMARY KEY,
  project_id            TEXT NOT NULL REFERENCES projects(id),
  objective             TEXT NOT NULL,
  status                TEXT NOT NULL DEFAULT 'draft',
  integration_branch    TEXT,
  integration_base      TEXT,
  integration_auto_land INTEGER NOT NULL DEFAULT 0,
  created_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
  id              TEXT PRIMARY KEY,
  plan_id         TEXT NOT NULL REFERENCES plans(id),
  title           TEXT NOT NULL,
  description     TEXT,
  status          TEXT NOT NULL DEFAULT 'todo',
  deps_json       TEXT,
  labels_json     TEXT,
  acceptance_json TEXT,
  risk_notes      TEXT,
  created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  id            TEXT PRIMARY KEY,
  task_id       TEXT NOT NULL REFERENCES tasks(id),
  role          TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'queued',
  attempt       INTEGER NOT NULL DEFAULT 1,
  agent_name    TEXT,
  worktree_path TEXT,
  branch        TEXT,
  base_sha      TEXT,
  head_sha      TEXT,
  started_at    TEXT,
  ended_at      TEXT
);

CREATE TABLE IF NOT EXISTS artifacts (
  id         TEXT PRIMARY KEY,
  run_id     TEXT NOT NULL REFERENCES runs(id),
  kind       TEXT NOT NULL,
  path       TEXT NOT NULL,
  meta_json  TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
  id           TEXT PRIMARY KEY,
  plan_id      TEXT,
  task_id      TEXT,
  run_id       TEXT,
  from_actor   TEXT NOT NULL,
  to_actor     TEXT NOT NULL,
  type         TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  reply_to     TEXT,
  delivered    INTEGER NOT NULL DEFAULT 0,
  created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_chunks (
  id                TEXT PRIMARY KEY,
  agent_name        TEXT NOT NULL,
  layer             TEXT NOT NULL,
  project_id        TEXT,
  file_path         TEXT NOT NULL,
  title             TEXT,
  tags_json         TEXT,
  outcome           TEXT,
  status            TEXT NOT NULL DEFAULT 'proposed',
  rejection_reason  TEXT,
  provenance_json   TEXT,
  last_validated_at TEXT,
  created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_agent   ON memory_chunks(agent_name);
CREATE INDEX IF NOT EXISTS idx_memory_layer   ON memory_chunks(layer);
CREATE INDEX IF NOT EXISTS idx_memory_project ON memory_chunks(project_id);
CREATE INDEX IF NOT EXISTS idx_memory_status  ON memory_chunks(status);

CREATE TABLE IF NOT EXISTS skill_files (
  id         TEXT PRIMARY KEY,
  role       TEXT NOT NULL,
  file_path  TEXT NOT NULL,
  title      TEXT,
  tags_json  TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
  id           TEXT PRIMARY KEY,
  project_id   TEXT NOT NULL REFERENCES projects(id),
  participant  TEXT NOT NULL,
  title        TEXT,
  created_at   TEXT NOT NULL,
  last_turn_at TEXT
);

CREATE TABLE IF NOT EXISTS conversation_turns (
  id              TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  role            TEXT NOT NULL,
  content         TEXT NOT NULL,
  plan_id         TEXT,
  task_id         TEXT,
  run_id          TEXT,
  created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conv_turns_conv ON conversation_turns(conversation_id);

CREATE TABLE IF NOT EXISTS escalations (
  id                      TEXT PRIMARY KEY,
  project_id              TEXT NOT NULL REFERENCES projects(id),
  task_id                 TEXT REFERENCES tasks(id),
  run_id                  TEXT REFERENCES runs(id),
  severity                INTEGER NOT NULL DEFAULT 1,
  reason                  TEXT NOT NULL,
  status                  TEXT NOT NULL DEFAULT 'open',
  auto_bump_after_minutes INTEGER,
  created_at              TEXT NOT NULL,
  bumped_at               TEXT,
  resolved_at             TEXT
);

CREATE INDEX IF NOT EXISTS idx_esc_status ON escalations(status);

CREATE TABLE IF NOT EXISTS chronicle (
  id           TEXT PRIMARY KEY,
  ts           TEXT NOT NULL,
  project_id   TEXT,
  plan_id      TEXT,
  task_id      TEXT,
  run_id       TEXT,
  actor        TEXT NOT NULL,
  event_type   TEXT NOT NULL,
  payload_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_chronicle_task  ON chronicle(task_id);
CREATE INDEX IF NOT EXISTS idx_chronicle_run   ON chronicle(run_id);
CREATE INDEX IF NOT EXISTS idx_chronicle_type  ON chronicle(event_type);
CREATE INDEX IF NOT EXISTS idx_chronicle_ts    ON chronicle(ts);
`
