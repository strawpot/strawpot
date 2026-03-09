import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";

export function useRoles() {
  return useQuery({
    queryKey: queryKeys.roles.all,
    queryFn: () => api.get<string[]>("/roles"),
  });
}
