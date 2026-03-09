import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";
import type { ResourceConfig } from "@/api/types";

export function useResourceConfig(
  type: string,
  name: string,
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: queryKeys.registry.config(type, name),
    queryFn: () => api.get<ResourceConfig>(`/registry/${type}/${name}/config`),
    enabled: options?.enabled ?? !!name,
  });
}
