import { useMutation } from "@tanstack/react-query";
import { api } from "@/api/client";

interface RespondBody {
  request_id: string;
  text: string;
}

export function useRespondToAskUser(runId: string) {
  return useMutation({
    mutationFn: (body: RespondBody) =>
      api.post<{ ok: boolean }>(`/sessions/${runId}/respond`, body),
  });
}
