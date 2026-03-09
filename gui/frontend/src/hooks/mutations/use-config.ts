import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";

export function useSaveGlobalConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      api.put<Record<string, unknown>>("/config/global", data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.config.global });
    },
  });
}

export function useSaveProjectConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      projectId,
      data,
    }: {
      projectId: number;
      data: Record<string, unknown>;
    }) =>
      api.put<Record<string, unknown>>(
        `/projects/${projectId}/config`,
        data,
      ),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({
        queryKey: queryKeys.projects.config(variables.projectId),
      });
    },
  });
}
