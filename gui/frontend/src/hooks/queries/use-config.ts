import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";

interface GlobalConfigResponse {
  values: Record<string, unknown>;
  defaults: Record<string, unknown>;
}

export function useGlobalConfig() {
  return useQuery({
    queryKey: queryKeys.config.global,
    queryFn: () => api.get<GlobalConfigResponse>("/config/global"),
  });
}
