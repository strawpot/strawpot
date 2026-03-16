import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";
import type { InstallResult } from "@/api/types";

export function useStartIntegration() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      api.post<{ name: string; status: string; pid: number }>(`/integrations/${name}/start`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.integrations.all });
    },
  });
}

export function useStopIntegration() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      api.post<{ name: string; status: string }>(`/integrations/${name}/stop`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.integrations.all });
    },
  });
}

export function useSaveIntegrationConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, config_values }: { name: string; config_values: Record<string, string> }) =>
      api.put<{ ok: boolean }>(`/integrations/${name}/config`, { config_values }),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: queryKeys.integrations.config(variables.name) });
      qc.invalidateQueries({ queryKey: queryKeys.integrations.all });
    },
  });
}

export function useInstallIntegration() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      api.post<InstallResult>("/integrations/install", { name }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.integrations.all });
    },
  });
}

export function useUninstallIntegration() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      api.delete<InstallResult>(`/integrations/${name}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.integrations.all });
    },
  });
}

export function useUpdateIntegration() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      api.post<InstallResult>("/integrations/update", { name }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.integrations.all });
    },
  });
}

export function useReinstallIntegration() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      api.post<InstallResult>("/integrations/reinstall", { name }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.integrations.all });
    },
  });
}

export function useSetAutoStart() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean }) =>
      api.put<{ ok: boolean; auto_start: boolean }>(`/integrations/${name}/auto-start`, { enabled }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.integrations.all });
    },
  });
}

export function useDeleteIntegrationConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) =>
      api.delete<{ ok: boolean }>(`/integrations/${name}/config`),
    onSuccess: (_data, name) => {
      qc.invalidateQueries({ queryKey: queryKeys.integrations.config(name) });
      qc.invalidateQueries({ queryKey: queryKeys.integrations.all });
    },
  });
}
