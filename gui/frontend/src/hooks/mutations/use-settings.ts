import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";

/**
 * Save (create or update) a single setting by key.
 */
export function useSaveSetting(key: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (value: string) =>
      api.put<{ key: string; value: string }>(`/settings/${key}`, { value }),
    onSuccess: (_res, value) => {
      qc.setQueryData(queryKeys.settings.detail(key), value);
      qc.invalidateQueries({ queryKey: queryKeys.settings.all });
    },
  });
}
