import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";
import type { Conversation, ConversationList, ImuConversation } from "@/api/types";

interface CreateConversationBody {
  project_id: number;
  title?: string;
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
      api.post<{ run_id: string; conversation_id: number }>(
        `/conversations/${conversationId}/tasks`,
        body,
      ),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: queryKeys.conversations.detail(conversationId),
      });
      qc.invalidateQueries({ queryKey: ["sessions"] });
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
