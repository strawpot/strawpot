import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";
import type { Project, ProjectFile } from "@/api/types";

export function useProjects() {
  return useQuery({
    queryKey: queryKeys.projects.all,
    queryFn: () => api.get<Project[]>("/projects"),
  });
}

export function useProject(id: number, options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: queryKeys.projects.detail(id),
    queryFn: () => api.get<Project>(`/projects/${id}`),
    enabled: options?.enabled,
  });
}

export interface ProjectConfig {
  merged: Record<string, unknown>;
  merged_nested: Record<string, unknown>;
  project: Record<string, unknown>;
  global: Record<string, unknown>;
}

export function useProjectFiles(id: number) {
  return useQuery({
    queryKey: queryKeys.projects.files(id),
    queryFn: () => api.get<ProjectFile[]>(`/projects/${id}/files`),
  });
}

export function useProjectConfig(
  id: number,
  options?: { enabled?: boolean },
) {
  return useQuery({
    queryKey: queryKeys.projects.config(id),
    queryFn: () => api.get<ProjectConfig>(`/projects/${id}/config`),
    enabled: options?.enabled,
  });
}
