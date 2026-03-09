export const queryKeys = {
  projects: {
    all: ["projects"] as const,
    detail: (id: number) => ["projects", id] as const,
    config: (id: number) => ["projects", id, "config"] as const,
    sessions: (id: number) => ["projects", id, "sessions"] as const,
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
};
