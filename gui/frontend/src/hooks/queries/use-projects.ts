import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";
import type { Project } from "@/api/types";

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

interface ProjectConfig {
  merged: {
    orchestrator_role: string;
    runtime: string;
    isolation: string;
    merge_strategy: string;
    [key: string]: unknown;
  };
}

export function useProjectConfig(id: number) {
  return useQuery({
    queryKey: queryKeys.projects.config(id),
    queryFn: () => api.get<ProjectConfig>(`/projects/${id}/config`),
  });
}
