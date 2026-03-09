import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { display_name: string; working_dir: string }) =>
      api.post("/projects", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.projects.all });
    },
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (projectId: number) => api.delete(`/projects/${projectId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.projects.all });
    },
  });
}
