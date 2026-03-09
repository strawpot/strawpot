import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";
import type { InstallResult } from "@/api/types";

export function useInstallResource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { type: string; name: string }) =>
      api.post<InstallResult>("/registry/install", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry"] });
    },
  });
}

export function useUninstallResource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ type, name }: { type: string; name: string }) =>
      api.delete<InstallResult>(`/registry/${type}/${name}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry"] });
    },
  });
}

export function useUpdateResource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { type: string; name: string }) =>
      api.post<InstallResult>("/registry/update", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry"] });
    },
  });
}

export function useReinstallResource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { type: string; name: string }) =>
      api.post<InstallResult>("/registry/reinstall", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry"] });
    },
  });
}

export function useSaveResourceConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      type,
      name,
      env_values,
      params_values,
    }: {
      type: string;
      name: string;
      env_values?: Record<string, string>;
      params_values?: Record<string, unknown>;
    }) =>
      api.put<{ ok: boolean }>(`/registry/${type}/${name}/config`, {
        env_values,
        params_values,
      }),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({
        queryKey: queryKeys.registry.config(variables.type, variables.name),
      });
    },
  });
}
