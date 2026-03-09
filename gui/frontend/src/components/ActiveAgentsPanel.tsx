import { useQueries } from "@tanstack/react-query";
import { useRunningSessions } from "@/hooks/queries/use-sessions";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";
import AgentActivityCard from "@/components/AgentActivityCard";
import type { SessionDetail } from "@/api/types";

const MAX_CARDS = 8;

interface AgentEntry {
  runId: string;
  projectId: number;
  agentId: string;
  role: string;
  runtime: string;
  startedAt: string;
}

export default function ActiveAgentsPanel() {
  const running = useRunningSessions();
  const runningSessions = running.data?.items ?? [];

  // Fetch session details in parallel to get agents map
  const detailQueries = useQueries({
    queries: runningSessions.slice(0, MAX_CARDS).map((s) => ({
      queryKey: queryKeys.sessions.detail(s.project_id, s.run_id),
      queryFn: () =>
        api.get<SessionDetail>(
          `/projects/${s.project_id}/sessions/${s.run_id}`,
        ),
      staleTime: 10_000,
    })),
  });

  // Flatten all agents across sessions
  const agents: AgentEntry[] = [];
  for (const q of detailQueries) {
    if (!q.data) continue;
    const session = q.data;
    for (const [agentId, info] of Object.entries(session.agents)) {
      agents.push({
        runId: session.run_id,
        projectId: session.project_id,
        agentId,
        role: info.role,
        runtime: info.runtime,
        startedAt: info.started_at,
      });
    }
  }

  if (agents.length === 0) return null;

  const visible = agents.slice(0, MAX_CARDS);
  const overflow = agents.length - MAX_CARDS;

  return (
    <section className="space-y-3">
      <h2 className="text-sm font-medium text-muted-foreground">
        Active Agents ({agents.length})
      </h2>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(320px,1fr))] gap-3">
        {visible.map((a) => (
          <AgentActivityCard
            key={`${a.runId}:${a.agentId}`}
            runId={a.runId}
            projectId={a.projectId}
            agentId={a.agentId}
            role={a.role}
            runtime={a.runtime}
            startedAt={a.startedAt}
          />
        ))}
      </div>
      {overflow > 0 && (
        <p className="text-xs text-muted-foreground">
          +{overflow} more agent{overflow !== 1 ? "s" : ""} running
        </p>
      )}
    </section>
  );
}
