import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";
import type { InstallResult } from "@/api/types";

export function useInstallProjectResource(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { type: string; name: string }) =>
      api.post<InstallResult>(`/projects/${projectId}/resources/install`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.projects.resources(projectId) });
    },
  });
}

export function useUninstallProjectResource(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ type, name }: { type: string; name: string }) =>
      api.delete<InstallResult>(
        `/projects/${projectId}/resources/${type}/${name}`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.projects.resources(projectId) });
    },
  });
}

export function useUpdateProjectResource(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { type: string; name: string }) =>
      api.post<InstallResult>(`/projects/${projectId}/resources/update`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.projects.resources(projectId) });
    },
  });
}

export function useUpdateAllProjectResources(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => {
      const controller = new AbortController();
      setTimeout(() => controller.abort(), 150_000);
      return fetch(`/api/projects/${projectId}/resources/update-all`, {
        method: "POST",
        signal: controller.signal,
      }).then(async (res) => {
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        return res.json() as Promise<InstallResult>;
      });
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: queryKeys.projects.resources(projectId) });
    },
  });
}

export function useReinstallProjectResource(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { type: string; name: string }) =>
      api.post<InstallResult>(`/projects/${projectId}/resources/reinstall`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.projects.resources(projectId) });
    },
  });
}

export function useSaveProjectResourceConfig(projectId: number) {
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
      api.put<{ ok: boolean }>(
        `/projects/${projectId}/resources/${type}/${name}/config`,
        { env_values, params_values },
      ),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({
        queryKey: queryKeys.projects.resourceConfig(
          projectId,
          variables.type,
          variables.name,
        ),
      });
    },
  });
}
