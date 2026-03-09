import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { InstallResult } from "@/api/types";

export function useInstallResource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { type: string; name: string }) =>
      api.post<InstallResult>("/registry/install", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry"] });
    },
  });
}

export function useUninstallResource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ type, name }: { type: string; name: string }) =>
      api.delete<InstallResult>(`/registry/${type}/${name}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["registry"] });
    },
  });
}
