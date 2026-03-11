import { useEffect, useRef, useState } from "react";
import type { AskUserPending, ChatMessage } from "@/api/types";

/**
 * Listens to the session tree SSE for `ask_user`, `ask_user_resolved`,
 * and `chat_history` events. Returns the current pending question and
 * any persisted chat messages from previous connections.
 */
export function useAskUserSSE(
  runId: string,
  active: boolean,
): { pendingAskUser: AskUserPending | null; chatMessages: ChatMessage[] } {
  const [pendingAskUser, setPendingAskUser] = useState<AskUserPending | null>(
    null,
  );
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const backoffMs = useRef(1000);

  useEffect(() => {
    if (!active) {
      setPendingAskUser(null);
      setChatMessages([]);
      return;
    }

    function connect() {
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
          setPendingAskUser(data);
        } catch {
          /* ignore */
        }
      });

      es.addEventListener("ask_user_resolved", () => {
        setPendingAskUser(null);
      });

      es.onerror = () => {
        es.close();
        esRef.current = null;
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

  return { pendingAskUser, chatMessages };
}
