import { useQuery, useInfiniteQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";
import type { Conversation, ConversationList, RecentConversation } from "@/api/types";

export function useConversation(
  id: number,
  options?: { refetchInterval?: number | false },
) {
  return useQuery({
    queryKey: queryKeys.conversations.detail(id),
    queryFn: () => api.get<Conversation>(`/conversations/${id}`),
    ...options,
  });
}

export function useConversationInfinite(
  id: number,
  options?: { refetchInterval?: number | false },
) {
  return useInfiniteQuery({
    queryKey: queryKeys.conversations.detail(id),
    queryFn: ({ pageParam }: { pageParam: string | null }) =>
      api.get<Conversation>(
        `/conversations/${id}?limit=20${pageParam ? `&before_id=${encodeURIComponent(pageParam)}` : ""}`,
      ),
    initialPageParam: null as string | null,
    getPreviousPageParam: (firstPage) =>
      firstPage.has_more ? (firstPage.sessions[0]?.run_id ?? null) : null,
    getNextPageParam: () => null,
    ...options,
  });
}

export function useRecentConversations(limit = 10) {
  return useQuery({
    queryKey: ["conversations", "recent", limit],
    queryFn: () => api.get<RecentConversation[]>(`/conversations/recent?limit=${limit}`),
  });
}

export function useProjectConversations(
  projectId: number,
  page = 1,
  perPage = 20,
) {
  return useQuery({
    queryKey: [...queryKeys.conversations.all(projectId), page, perPage],
    queryFn: () =>
      api.get<ConversationList>(
        `/projects/${projectId}/conversations?page=${page}&per_page=${perPage}`,
      ),
    enabled: projectId > 0,
  });
}
