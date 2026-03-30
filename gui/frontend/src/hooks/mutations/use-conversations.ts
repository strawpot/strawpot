import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";
import type { Conversation, ConversationList, ImuConversation } from "@/api/types";
import type { InfiniteData } from "@tanstack/react-query";

interface CreateConversationBody {
  project_id: number;
  title?: string;
  parent_conversation_id?: number;
}

interface SubmitTaskBody {
  task: string;
  role?: string;
  context_files?: string[];
  interactive?: boolean;
  system_prompt?: string;
  runtime?: string;
  memory?: string;
  max_num_delegations?: number;
  cache_delegations?: boolean;
  cache_max_entries?: number;
  cache_ttl_seconds?: number;
}

export function useCreateConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateConversationBody) =>
      api.post<Conversation>("/conversations", body),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({
        queryKey: queryKeys.conversations.all(variables.project_id),
      });
    },
  });
}

export function useSubmitConversationTask(conversationId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SubmitTaskBody) =>
      api.post<{ run_id?: string; queued?: boolean; conversation_id: number }>(
        `/conversations/${conversationId}/tasks`,
        body,
      ),
    onError: (error: Error) => {
      // Silently ignore 409 Conflict — backend duplicate submission guard.
      // The first request succeeded; the duplicate was correctly rejected.
      if (error instanceof ApiError && error.status === 409) return;
      throw error;
    },
    onSuccess: (data, variables) => {
      if (data.queued) {
        // Optimistically append to queued_tasks in the infinite query cache
        qc.setQueryData<InfiniteData<Conversation>>(
          queryKeys.conversations.detail(conversationId),
          (old) => {
            if (!old) return old;
            const pages = old.pages.map((page, i) => {
              if (i !== 0) return page;
              const newTask = {
                id: -Date.now(), // temporary ID until refetch
                task: variables.task,
                source: "user",
                source_id: null,
                created_at: new Date().toISOString(),
              };
              const queued = [...(page.queued_tasks ?? []), newTask];
              return {
                ...page,
                queued_tasks: queued,
                pending_task: queued.map((q) => q.task).join("\n\n") || null,
              };
            });
            return { ...old, pages };
          },
        );
      }
      qc.invalidateQueries({
        queryKey: queryKeys.conversations.detail(conversationId),
      });
      qc.invalidateQueries({ queryKey: ["sessions"] });
      // Also refresh the Imu conversation list so sidebar title updates
      qc.invalidateQueries({ queryKey: ["imu", "conversations"] });
    },
  });
}

export function useRenameConversation(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ conversationId, title }: { conversationId: number; title: string | null }) =>
      api.patch<Conversation>(`/conversations/${conversationId}`, { title }),
    onSuccess: (_data, { conversationId }) => {
      qc.invalidateQueries({ queryKey: queryKeys.conversations.all(projectId) });
      qc.invalidateQueries({ queryKey: queryKeys.conversations.detail(conversationId) });
    },
  });
}

export function useCancelPendingTask(conversationId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.delete(`/conversations/${conversationId}/pending_task`),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: queryKeys.conversations.detail(conversationId),
      });
    },
  });
}

export function useCancelQueuedTask(conversationId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (taskId: number) =>
      api.delete(`/conversations/${conversationId}/queued_tasks/${taskId}`),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: queryKeys.conversations.detail(conversationId),
      });
    },
  });
}

export function useCreateImuConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post<Pick<ImuConversation, "id" | "title" | "created_at" | "updated_at">>(
        "/imu/conversations",
        {},
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["imu", "conversations"] });
    },
  });
}

export function useRenameImuConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ conversationId, title }: { conversationId: number; title: string | null }) =>
      api.patch<Conversation>(`/conversations/${conversationId}`, { title }),
    onSuccess: (_data, { conversationId }) => {
      qc.invalidateQueries({ queryKey: ["imu", "conversations"] });
      qc.invalidateQueries({ queryKey: queryKeys.conversations.detail(conversationId) });
    },
  });
}

export function useDeleteImuConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (conversationId: number) => api.delete(`/conversations/${conversationId}`),
    onMutate: async (conversationId: number) => {
      await qc.cancelQueries({ queryKey: ["imu", "conversations"] });
      const previous = qc.getQueryData<ImuConversation[]>(["imu", "conversations"]);
      qc.setQueryData<ImuConversation[]>(["imu", "conversations"], (old) =>
        old ? old.filter((c) => c.id !== conversationId) : old,
      );
      // Remove detail cache so a reused rowid doesn't serve stale data
      qc.removeQueries({ queryKey: queryKeys.conversations.detail(conversationId) });
      return { previous };
    },
    onError: (_err, _id, context) => {
      if (context?.previous) {
        qc.setQueryData(["imu", "conversations"], context.previous);
      }
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["imu", "conversations"] });
    },
  });
}

export function useDeleteConversation(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (conversationId: number) =>
      api.delete(`/conversations/${conversationId}`),
    onMutate: async (conversationId: number) => {
      await qc.cancelQueries({ queryKey: queryKeys.conversations.all(projectId) });
      const previous = qc.getQueryData<ConversationList>(queryKeys.conversations.all(projectId));
      qc.setQueryData<ConversationList>(queryKeys.conversations.all(projectId), (old) => {
        if (!old) return old;
        return { ...old, items: old.items.filter((c) => c.id !== conversationId), total: old.total - 1 };
      });
      qc.removeQueries({ queryKey: queryKeys.conversations.detail(conversationId) });
      return { previous };
    },
    onError: (_err, _id, context) => {
      if (context?.previous) {
        qc.setQueryData(queryKeys.conversations.all(projectId), context.previous);
      }
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: queryKeys.conversations.all(projectId) });
    },
  });
}
