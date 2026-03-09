import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";
import type { Resource, ResourceDetail } from "@/api/types";

export function useResources(type: string) {
  return useQuery({
    queryKey: queryKeys.registry.list(type),
    queryFn: () => api.get<Resource[]>(`/registry/${type}`),
  });
}

export function useResourceDetail(
  type: string,
  name: string,
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: queryKeys.registry.detail(type, name),
    queryFn: () => api.get<ResourceDetail>(`/registry/${type}/${name}`),
    enabled: options?.enabled ?? !!name,
  });
}
