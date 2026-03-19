import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { InstallResult } from "@/api/types";

interface IntegrationRef {
  name: string;
  projectId?: number;
}

function pidParam(projectId?: number) {
  return projectId != null ? `?project_id=${projectId}` : "";
}

function invalidateAll(qc: ReturnType<typeof useQueryClient>) {
  qc.invalidateQueries({ queryKey: ["integrations"] });
}

export function useStartIntegration() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, projectId }: IntegrationRef) =>
      api.post<{ name: string; status: string; pid: number }>(
        `/integrations/${name}/start${pidParam(projectId)}`,
      ),
    onSuccess: () => invalidateAll(qc),
  });
}

export function useStopIntegration() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, projectId }: IntegrationRef) =>
      api.post<{ name: string; status: string }>(
        `/integrations/${name}/stop${pidParam(projectId)}`,
      ),
    onSuccess: () => invalidateAll(qc),
  });
}

export function useSaveIntegrationConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      name,
      config_values,
      projectId,
    }: IntegrationRef & { config_values: Record<string, string> }) =>
      api.put<{ ok: boolean }>(
        `/integrations/${name}/config${pidParam(projectId)}`,
        { config_values },
      ),
    onSuccess: () => invalidateAll(qc),
  });
}

export function useInstallIntegration() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, projectId }: IntegrationRef) =>
      api.post<InstallResult>("/integrations/install", {
        name,
        ...(projectId != null && { project_id: projectId }),
      }),
    onSuccess: () => invalidateAll(qc),
  });
}

export function useUninstallIntegration() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, projectId }: IntegrationRef) =>
      api.delete<InstallResult>(
        `/integrations/${name}${pidParam(projectId)}`,
      ),
    onSuccess: () => invalidateAll(qc),
  });
}

export function useUpdateIntegration() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, projectId }: IntegrationRef) =>
      api.post<InstallResult>("/integrations/update", {
        name,
        ...(projectId != null && { project_id: projectId }),
      }),
    onSuccess: () => invalidateAll(qc),
  });
}

export function useReinstallIntegration() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, projectId }: IntegrationRef) =>
      api.post<InstallResult>("/integrations/reinstall", {
        name,
        ...(projectId != null && { project_id: projectId }),
      }),
    onSuccess: () => invalidateAll(qc),
  });
}

export function useSetAutoStart() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      name,
      enabled,
      projectId,
    }: IntegrationRef & { enabled: boolean }) =>
      api.put<{ ok: boolean; auto_start: boolean }>(
        `/integrations/${name}/auto-start${pidParam(projectId)}`,
        { enabled },
      ),
    onSuccess: () => invalidateAll(qc),
  });
}

export function useDeleteIntegrationConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, projectId }: IntegrationRef) =>
      api.delete<{ ok: boolean }>(
        `/integrations/${name}/config${pidParam(projectId)}`,
      ),
    onSuccess: () => invalidateAll(qc),
  });
}
