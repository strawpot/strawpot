export const queryKeys = {
  projects: {
    all: ["projects"] as const,
    detail: (id: number) => ["projects", id] as const,
    config: (id: number) => ["projects", id, "config"] as const,
    sessions: (id: number) => ["projects", id, "sessions"] as const,
    files: (id: number) => ["projects", id, "files"] as const,
    stats: (id: number, period: string) => ["projects", id, "stats", period] as const,
    resources: (id: number) => ["projects", id, "resources"] as const,
    resourceDetail: (id: number, type: string, name: string) =>
      ["projects", id, "resources", type, name] as const,
    resourceConfig: (id: number, type: string, name: string) =>
      ["projects", id, "resources", type, name, "config"] as const,
  },
  sessions: {
    all: (filters?: Record<string, string>) => ["sessions", filters] as const,
    detail: (projectId: number, runId: string) =>
      ["sessions", projectId, runId] as const,
    running: () => ["sessions", { status: "running" }] as const,
  },
  roles: {
    all: ["roles"] as const,
  },
  config: {
    global: ["config", "global"] as const,
  },
  registry: {
    list: (type: string) => ["registry", type] as const,
    detail: (type: string, name: string) => ["registry", type, name] as const,
    config: (type: string, name: string) =>
      ["registry", type, name, "config"] as const,
    validate: (name: string) =>
      ["registry", "agents", name, "validate"] as const,
  },
  schedules: {
    all: ["schedules"] as const,
    detail: (id: number) => ["schedules", id] as const,
    history: (id: number) => ["schedules", id, "history"] as const,
    runs: ["schedules", "runs"] as const,
  },
  conversations: {
    all: (projectId: number) => ["conversations", projectId] as const,
    detail: (id: number) => ["conversations", "detail", id] as const,
  },
  integrations: {
    all: (projectId?: number) => ["integrations", projectId] as const,
    detail: (name: string, projectId?: number) =>
      ["integrations", name, projectId] as const,
    config: (name: string, projectId?: number) =>
      ["integrations", name, "config", projectId] as const,
  },
};
