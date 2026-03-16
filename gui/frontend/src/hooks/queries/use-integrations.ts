import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";
import type { Integration, IntegrationDetail, IntegrationConfig } from "@/api/types";

export function useIntegrations() {
  return useQuery({
    queryKey: queryKeys.integrations.all,
    queryFn: () => api.get<Integration[]>("/integrations"),
    refetchInterval: 10_000,
  });
}

export function useIntegrationDetail(name: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.integrations.detail(name),
    queryFn: () => api.get<IntegrationDetail>(`/integrations/${name}`),
    enabled: options?.enabled ?? !!name,
  });
}

export function useIntegrationConfig(name: string, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.integrations.config(name),
    queryFn: () => api.get<IntegrationConfig>(`/integrations/${name}/config`),
    enabled: options?.enabled ?? !!name,
  });
}
