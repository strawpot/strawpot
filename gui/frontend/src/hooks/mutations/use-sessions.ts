import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";

interface LaunchSessionBody {
  project_id: number;
  task: string;
  role?: string;
  overrides?: Record<string, unknown>;
  context_files?: string[];
  system_prompt?: string;
  interactive?: boolean;
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
      qc.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}

export function useDeleteSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => api.delete(`/sessions/${runId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sessions"] });
      qc.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}

export function useCancelAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      runId,
      agentId,
      force = false,
    }: {
      runId: string;
      agentId: string;
      force?: boolean;
    }) =>
      api.post<{ status: string; message: string }>(
        `/sessions/${runId}/agents/${agentId}/cancel`,
        { force },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}

export function useCancelSession() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      runId,
      force = false,
    }: {
      runId: string;
      force?: boolean;
    }) =>
      api.post<{ status: string; message: string }>(
        `/sessions/${runId}/cancel`,
        { force },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["sessions"] });
      qc.invalidateQueries({ queryKey: ["conversations"] });
    },
  });
}
