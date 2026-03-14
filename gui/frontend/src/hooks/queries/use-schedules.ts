import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";
import type { Schedule, ScheduleRunList, Session } from "@/api/types";

export function useSchedules(type?: "recurring" | "one_time") {
  return useQuery({
    queryKey: type
      ? [...queryKeys.schedules.all, type]
      : queryKeys.schedules.all,
    queryFn: () =>
      api.get<Schedule[]>(
        type ? `/schedules?type=${type}` : "/schedules",
      ),
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

export function useScheduleRuns(page = 1, perPage = 20) {
  return useQuery({
    queryKey: [...queryKeys.schedules.runs, page, perPage],
    queryFn: () =>
      api.get<ScheduleRunList>(
        `/schedules/runs?page=${page}&per_page=${perPage}`,
      ),
  });
}
