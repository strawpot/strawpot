import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";
import type { Schedule } from "@/api/types";

interface CreateScheduleBody {
  name: string;
  project_id: number;
  task: string;
  cron_expr: string;
  role?: string;
  system_prompt?: string;
  skip_if_running?: boolean;
  conversation_id?: number | null;
}

interface CreateOneTimeScheduleBody {
  name: string;
  project_id: number;
  task: string;
  run_at: string;
  role?: string;
  system_prompt?: string;
  conversation_id?: number | null;
}

interface UpdateScheduleBody {
  name?: string;
  task?: string;
  cron_expr?: string;
  run_at?: string;
  role?: string;
  system_prompt?: string;
  skip_if_running?: boolean;
  conversation_id?: number | null;
}

export function useCreateSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateScheduleBody) =>
      api.post<Schedule>("/schedules", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.schedules.all });
    },
  });
}

export function useCreateOneTimeSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateOneTimeScheduleBody) =>
      api.post<Schedule>("/schedules/one-time", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.schedules.all });
    },
  });
}

export function useUpdateSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & UpdateScheduleBody) =>
      api.put<Schedule>(`/schedules/${id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.schedules.all });
    },
  });
}

export function useDeleteSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.delete(`/schedules/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.schedules.all });
    },
  });
}

export function useToggleSchedule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enable }: { id: number; enable: boolean }) =>
      api.post<Schedule>(`/schedules/${id}/${enable ? "enable" : "disable"}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.schedules.all });
    },
  });
}
