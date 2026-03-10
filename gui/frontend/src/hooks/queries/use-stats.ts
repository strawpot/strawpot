import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";
import type { ProjectStats } from "@/api/types";

export function useProjectStats(projectId: number, period = "30d") {
  return useQuery({
    queryKey: queryKeys.projects.stats(projectId, period),
    queryFn: () =>
      api.get<ProjectStats>(
        `/projects/${projectId}/stats?period=${period}`,
      ),
  });
}
