import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";
import type { Integration, IntegrationDetail, IntegrationConfig } from "@/api/types";

function pidParam(projectId?: number) {
  return projectId != null ? `?project_id=${projectId}` : "";
}

export function useIntegrations(projectId?: number) {
  return useQuery({
    queryKey: queryKeys.integrations.all(projectId),
    queryFn: () => api.get<Integration[]>(`/integrations${pidParam(projectId)}`),
    refetchInterval: 10_000,
  });
}

export function useIntegrationDetail(
  name: string,
  options?: { enabled?: boolean; projectId?: number },
) {
  const projectId = options?.projectId;
  return useQuery({
    queryKey: queryKeys.integrations.detail(name, projectId),
    queryFn: () =>
      api.get<IntegrationDetail>(`/integrations/${name}${pidParam(projectId)}`),
    enabled: options?.enabled ?? !!name,
  });
}

export function useIntegrationConfig(
  name: string,
  options?: { enabled?: boolean; projectId?: number },
) {
  const projectId = options?.projectId;
  return useQuery({
    queryKey: queryKeys.integrations.config(name, projectId),
    queryFn: () =>
      api.get<IntegrationConfig>(`/integrations/${name}/config${pidParam(projectId)}`),
    enabled: options?.enabled ?? !!name,
  });
}
