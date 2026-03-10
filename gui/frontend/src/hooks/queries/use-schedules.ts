import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";
import type { Schedule, Session } from "@/api/types";

export function useSchedules() {
  return useQuery({
    queryKey: queryKeys.schedules.all,
    queryFn: () => api.get<Schedule[]>("/schedules"),
  });
}

export function useSchedule(id: number) {
  return useQuery({
    queryKey: queryKeys.schedules.detail(id),
    queryFn: () => api.get<Schedule>(`/schedules/${id}`),
    enabled: id > 0,
  });
}

export function useScheduleHistory(id: number) {
  return useQuery({
    queryKey: queryKeys.schedules.history(id),
    queryFn: () => api.get<Session[]>(`/schedules/${id}/history`),
    enabled: id > 0,
  });
}
