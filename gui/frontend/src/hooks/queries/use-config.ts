import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";

export function useGlobalConfig() {
  return useQuery({
    queryKey: queryKeys.config.global,
    queryFn: () => api.get<Record<string, unknown>>("/config/global"),
  });
}
