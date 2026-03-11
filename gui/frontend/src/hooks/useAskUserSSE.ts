import { useEffect, useRef, useState } from "react";
import type { AskUserPending, ChatMessage } from "@/api/types";

/**
 * Listens to the session tree SSE for `ask_user`, `ask_user_resolved`,
 * `chat_history`, and `stream_complete` events. Returns current pending
 * questions and any persisted chat messages from previous connections.
 *
 * Connects for all interactive sessions (including completed ones) so
 * that chat history is always available.
 */
export function useAskUserSSE(
  runId: string,
  active: boolean,
): { pendingAskUsers: AskUserPending[]; chatMessages: ChatMessage[] } {
  const [pendingAskUsers, setPendingAskUsers] = useState<AskUserPending[]>([]);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const backoffMs = useRef(1000);
  // When true, the server signaled the stream is done (terminal session).
  // Prevents reconnection loops for completed sessions.
  const streamDoneRef = useRef(false);

  useEffect(() => {
    if (!active) {
      setPendingAskUsers([]);
      setChatMessages([]);
      streamDoneRef.current = false;
      return;
    }

    function connect() {
      if (streamDoneRef.current) return;

      const es = new EventSource(`/api/sessions/${runId}/tree`);
      esRef.current = es;

      es.onopen = () => {
        backoffMs.current = 1000;
      };

      es.addEventListener("chat_history", (msg) => {
        try {
          const data = JSON.parse(msg.data) as { messages: ChatMessage[] };
          if (data.messages) {
            setChatMessages(data.messages);
          }
        } catch {
          /* ignore */
        }
      });

      es.addEventListener("ask_user", (msg) => {
        try {
          const data = JSON.parse(msg.data) as AskUserPending;
          setPendingAskUsers((prev) => {
            if (prev.some((p) => p.request_id === data.request_id)) return prev;
            return [...prev, data];
          });
        } catch {
          /* ignore */
        }
      });

      es.addEventListener("ask_user_resolved", (msg) => {
        try {
          const data = JSON.parse(msg.data) as { request_id?: string };
          if (data.request_id) {
            setPendingAskUsers((prev) =>
              prev.filter((p) => p.request_id !== data.request_id),
            );
          } else {
            setPendingAskUsers([]);
          }
        } catch {
          setPendingAskUsers([]);
        }
      });

      es.addEventListener("stream_complete", () => {
        streamDoneRef.current = true;
        es.close();
        esRef.current = null;
      });

      es.onerror = () => {
        es.close();
        esRef.current = null;
        if (streamDoneRef.current) return;
        reconnectTimer.current = setTimeout(() => {
          backoffMs.current = Math.min(backoffMs.current * 2, 15000);
          connect();
        }, backoffMs.current);
      };
    }

    connect();

    return () => {
      esRef.current?.close();
      esRef.current = null;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, [runId, active]);

  return { pendingAskUsers, chatMessages };
}
