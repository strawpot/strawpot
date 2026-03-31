import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { ApiError } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";

/**
 * Fetch a single setting by key. Returns null if the key does not exist (404).
 */
export function useSetting(key: string) {
  return useQuery({
    queryKey: queryKeys.settings.detail(key),
    queryFn: async () => {
      try {
        const res = await api.get<{ key: string; value: string }>(
          `/settings/${key}`,
        );
        return res.value;
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) return null;
        throw err;
      }
    },
  });
}
