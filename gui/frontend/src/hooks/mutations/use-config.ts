import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";

export function useSaveGlobalConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      api.put<Record<string, unknown>>("/config/global", data),
    onSuccess: (_response, savedData) => {
      // Immediately update the cache so ConfigForm re-syncs state
      qc.setQueryData(queryKeys.config.global, (old: unknown) => ({
        ...((old as Record<string, unknown>) ?? {}),
        values: savedData,
      }));
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
    onSuccess: (_response, variables) => {
      qc.setQueryData(
        queryKeys.projects.config(variables.projectId),
        (old: unknown) => ({
          ...((old as Record<string, unknown>) ?? {}),
          project: variables.data,
        }),
      );
      qc.invalidateQueries({
        queryKey: queryKeys.projects.config(variables.projectId),
      });
    },
  });
}
