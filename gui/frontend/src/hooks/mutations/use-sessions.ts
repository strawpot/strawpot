import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";

interface LaunchSessionBody {
  project_id: number;
  task: string;
  role?: string;
  overrides?: Record<string, string>;
  context_files?: string[];
  system_prompt?: string;
}

export function useLaunchSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: LaunchSessionBody) =>
      api.post<{ run_id: string }>("/sessions", body),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({
        queryKey: queryKeys.projects.sessions(variables.project_id),
      });
      qc.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}

export function useStopSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => api.post(`/sessions/${runId}/stop`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}
