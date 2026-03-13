import { useCallback, useEffect, useRef, useState } from "react";
import type { AskUserPending, ChatMessage, TraceEvent, TreeData } from "@/api/types";

const MAX_LOG_LINES = 10_000;

export interface AgentLogState {
  lines: string[];
  offset: number;
  done: boolean;
}

/**
 * Single bidirectional WebSocket connection per session.
 *
 * Replaces the former useAskUserSSE (which multiplexed over SSE)
 * and useAgentLogSSE (agent log streaming via SSE).
 *
 * Returns live state for the session and methods for replying to
 * ask_user questions and subscribing to agent logs through the
 * same connection.
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
  agentLogs: Map<string, AgentLogState>;
  respond: (requestId: string, text: string) => void;
  subscribeLogs: (agentId: string, offset?: number) => void;
  unsubscribeLogs: (agentId: string) => void;
} {
  const [pendingAskUsers, setPendingAskUsers] = useState<AskUserPending[]>([]);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [traceEvents, setTraceEvents] = useState<TraceEvent[]>([]);
  const [treeData, setTreeData] = useState<TreeData | null>(null);
  const [connected, setConnected] = useState(false);
  const [agentLogs, setAgentLogs] = useState<Map<string, AgentLogState>>(new Map());

  const wsRef = useRef<WebSocket | null>(null);
  const traceOffsetRef = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const backoffMs = useRef(1000);
  const streamDoneRef = useRef(false);
  // Track which agents are subscribed so we can re-subscribe on reconnect
  const subscribedAgentsRef = useRef<Set<string>>(new Set());

  const respond = useCallback((requestId: string, text: string) => {
    wsRef.current?.send(
      JSON.stringify({ type: "ask_user_response", request_id: requestId, text }),
    );
  }, []);

  const subscribeLogs = useCallback((agentId: string, offset?: number) => {
    subscribedAgentsRef.current.add(agentId);
    wsRef.current?.send(
      JSON.stringify({ type: "subscribe_logs", agent_id: agentId, ...(offset != null && { offset }) }),
    );
  }, []);

  const unsubscribeLogs = useCallback((agentId: string) => {
    subscribedAgentsRef.current.delete(agentId);
    setAgentLogs((prev) => {
      const next = new Map(prev);
      next.delete(agentId);
      return next;
    });
    wsRef.current?.send(
      JSON.stringify({ type: "unsubscribe_logs", agent_id: agentId }),
    );
  }, []);

  // Reset all session state when switching to a different session
  useEffect(() => {
    setPendingAskUsers([]);
    setChatMessages([]);
    setTraceEvents([]);
    setTreeData(null);
    setAgentLogs(new Map());
    subscribedAgentsRef.current.clear();
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
        // Re-subscribe to any previously subscribed agent logs
        for (const agentId of subscribedAgentsRef.current) {
          ws.send(JSON.stringify({ type: "subscribe_logs", agent_id: agentId }));
        }
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

          case "agent_log_snapshot": {
            const aid = msg.agent_id as string;
            const lines = (msg.lines as string[]) ?? [];
            const offset = (msg.offset as number) ?? 0;
            setAgentLogs((prev) => {
              const next = new Map(prev);
              next.set(aid, { lines: lines.slice(-MAX_LOG_LINES), offset, done: false });
              return next;
            });
            break;
          }

          case "agent_log_delta": {
            const aid = msg.agent_id as string;
            const newLines = (msg.lines as string[]) ?? [];
            const offset = (msg.offset as number) ?? 0;
            if (newLines.length > 0) {
              setAgentLogs((prev) => {
                const next = new Map(prev);
                const existing = next.get(aid);
                const merged = [...(existing?.lines ?? []), ...newLines];
                next.set(aid, {
                  lines: merged.length > MAX_LOG_LINES ? merged.slice(-MAX_LOG_LINES) : merged,
                  offset,
                  done: existing?.done ?? false,
                });
                return next;
              });
            }
            break;
          }

          case "agent_log_done": {
            const aid = msg.agent_id as string;
            setAgentLogs((prev) => {
              const next = new Map(prev);
              const existing = next.get(aid);
              if (existing) {
                next.set(aid, { ...existing, done: true });
              }
              return next;
            });
            break;
          }

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

  return {
    pendingAskUsers,
    chatMessages,
    traceEvents,
    treeData,
    connected,
    agentLogs,
    respond,
    subscribeLogs,
    unsubscribeLogs,
  };
}
