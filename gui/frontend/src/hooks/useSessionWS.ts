import { useCallback, useEffect, useRef, useState } from "react";
import type { AskUserPending, ChatMessage, TraceEvent, TreeData } from "@/api/types";

/**
 * Single bidirectional WebSocket connection per session.
 *
 * Replaces the former useAskUserSSE (which multiplexed over SSE).
 * Returns live state for the session and a `respond` function for
 * replying to ask_user questions through the same connection.
 *
 * On reconnect the client sends its last known trace byte offset so
 * the server resumes from there rather than replaying the full snapshot.
 */
export function useSessionWS(
  runId: string,
  active: boolean,
): {
  pendingAskUsers: AskUserPending[];
  chatMessages: ChatMessage[];
  traceEvents: TraceEvent[];
  treeData: TreeData | null;
  connected: boolean;
  respond: (requestId: string, text: string) => void;
} {
  const [pendingAskUsers, setPendingAskUsers] = useState<AskUserPending[]>([]);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [traceEvents, setTraceEvents] = useState<TraceEvent[]>([]);
  const [treeData, setTreeData] = useState<TreeData | null>(null);
  const [connected, setConnected] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const traceOffsetRef = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const backoffMs = useRef(1000);
  const streamDoneRef = useRef(false);

  const respond = useCallback((requestId: string, text: string) => {
    wsRef.current?.send(
      JSON.stringify({ type: "ask_user_response", request_id: requestId, text }),
    );
  }, []);

  // Reset all session state when switching to a different session
  useEffect(() => {
    setPendingAskUsers([]);
    setChatMessages([]);
    setTraceEvents([]);
    setTreeData(null);
    streamDoneRef.current = false;
    traceOffsetRef.current = 0;
  }, [runId]);

  useEffect(() => {
    if (!active) {
      setPendingAskUsers([]);
      setConnected(false);
      return;
    }

    function connect() {
      if (streamDoneRef.current) return;

      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${protocol}//${window.location.host}/ws/sessions/${runId}`;
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        backoffMs.current = 1000;
        ws.send(
          JSON.stringify({ type: "init", trace_offset: traceOffsetRef.current }),
        );
      };

      ws.onmessage = (event) => {
        let msg: Record<string, unknown>;
        try {
          msg = JSON.parse(event.data as string) as Record<string, unknown>;
        } catch {
          return;
        }

        switch (msg.type) {
          case "tree_snapshot":
          case "tree_delta": {
            const { type: _t, ...treeFields } = msg;
            setTreeData(treeFields as unknown as TreeData);
            break;
          }

          case "trace_snapshot":
            if (Array.isArray(msg.events)) {
              setTraceEvents(msg.events as TraceEvent[]);
            }
            if (typeof msg.next_offset === "number") {
              traceOffsetRef.current = msg.next_offset;
            }
            break;

          case "trace_delta":
            if (Array.isArray(msg.events)) {
              setTraceEvents((prev) => [...prev, ...(msg.events as TraceEvent[])]);
            }
            if (typeof msg.next_offset === "number") {
              traceOffsetRef.current = msg.next_offset;
            }
            break;

          case "ask_user": {
            const ask = msg as unknown as AskUserPending;
            setPendingAskUsers((prev) => {
              if (prev.some((p) => p.request_id === ask.request_id)) return prev;
              return [...prev, ask];
            });
            break;
          }

          case "ask_user_resolved":
            if (typeof msg.request_id === "string") {
              setPendingAskUsers((prev) =>
                prev.filter((p) => p.request_id !== (msg.request_id as string)),
              );
            } else {
              setPendingAskUsers([]);
            }
            break;

          case "chat_history":
            if (Array.isArray(msg.messages)) {
              setChatMessages(msg.messages as ChatMessage[]);
            }
            break;

          case "stream_complete":
            streamDoneRef.current = true;
            ws.close();
            wsRef.current = null;
            setConnected(false);
            break;

          default:
            break;
        }
      };

      ws.onclose = () => {
        wsRef.current = null;
        setConnected(false);
        if (streamDoneRef.current) return;
        reconnectTimer.current = setTimeout(() => {
          backoffMs.current = Math.min(backoffMs.current * 2, 15000);
          connect();
        }, backoffMs.current);
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      wsRef.current?.close();
      wsRef.current = null;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, [runId, active]);

  return { pendingAskUsers, chatMessages, traceEvents, treeData, connected, respond };
}
