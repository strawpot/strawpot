import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";
import type { SessionDetail, SessionList } from "@/api/types";

export function useSessions(filters?: Record<string, string>) {
  const params = filters
    ? "?" + new URLSearchParams(filters).toString()
    : "";
  return useQuery({
    queryKey: queryKeys.sessions.all(filters),
    queryFn: () => api.get<SessionList>(`/sessions${params}`),
  });
}

export function useRunningSessions() {
  return useSessions({ status: "running", per_page: "50" });
}

export function useRecentSessions() {
  return useSessions({ per_page: "10" });
}

export function useProjectSessions(projectId: number, page = 1, perPage = 20) {
  return useQuery({
    queryKey: [...queryKeys.projects.sessions(projectId), page, perPage],
    queryFn: () =>
      api.get<SessionList>(
        `/projects/${projectId}/sessions?page=${page}&per_page=${perPage}`,
      ),
  });
}

export function useSession(
  projectId: number,
  runId: string,
  options?: { refetchInterval?: number | false },
) {
  return useQuery({
    queryKey: queryKeys.sessions.detail(projectId, runId),
    queryFn: () =>
      api.get<SessionDetail>(`/projects/${projectId}/sessions/${runId}`),
    ...options,
  });
}
