import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";
import type { ProjectResource, ResourceDetail, ResourceConfig } from "@/api/types";

export function useProjectResources(projectId: number) {
  return useQuery({
    queryKey: queryKeys.projects.resources(projectId),
    queryFn: () => api.get<ProjectResource[]>(`/projects/${projectId}/resources`),
  });
}

export function useProjectResourceDetail(
  projectId: number,
  type: string,
  name: string,
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: queryKeys.projects.resourceDetail(projectId, type, name),
    queryFn: () =>
      api.get<ResourceDetail>(`/projects/${projectId}/resources/${type}/${name}`),
    enabled: options?.enabled ?? !!name,
  });
}

export function useProjectResourceConfig(
  projectId: number,
  type: string,
  name: string,
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: queryKeys.projects.resourceConfig(projectId, type, name),
    queryFn: () =>
      api.get<ResourceConfig>(
        `/projects/${projectId}/resources/${type}/${name}/config`,
      ),
    enabled: options?.enabled ?? !!name,
  });
}
