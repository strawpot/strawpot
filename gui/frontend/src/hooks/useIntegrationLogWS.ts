import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/api/client";

export interface IntegrationLogState {
  lines: string[];
  done: boolean;
  connected: boolean;
  clearLines: () => void;
}

/**
 * WebSocket hook for streaming integration adapter logs.
 *
 * Connects to `/api/integrations/{name}/logs/ws` and handles
 * the log_snapshot → log_delta → log_done protocol.
 */
export function useIntegrationLogWS(
  name: string | null,
  projectId?: number,
): IntegrationLogState {
  const [lines, setLines] = useState<string[]>([]);
  const [done, setDone] = useState(false);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  const connect = useCallback(() => {
    if (!name) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const pidQuery = projectId != null ? `?project_id=${projectId}` : "";
    const url = `${protocol}//${window.location.host}/api/integrations/${name}/logs/ws${pidQuery}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        switch (msg.type) {
          case "log_snapshot":
            setLines(msg.lines ?? []);
            break;
          case "log_delta":
            setLines((prev) => [...prev, ...(msg.lines ?? [])]);
            break;
          case "log_done":
            setDone(true);
            break;
          case "error":
            setDone(true);
            break;
        }
      } catch {
        /* ignore parse errors */
      }
    };

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
    };

    ws.onerror = () => {
      setConnected(false);
    };

    return ws;
  }, [name, projectId]);

  useEffect(() => {
    // Reset state on name change
    setLines([]);
    setDone(false);
    setConnected(false);

    const ws = connect();
    return () => {
      if (ws && ws.readyState <= WebSocket.OPEN) {
        ws.close();
      }
    };
  }, [connect]);

  const clearLines = useCallback(() => {
    if (name) {
      const pidQuery = projectId != null ? `?project_id=${projectId}` : "";
      api.delete(`/integrations/${name}/logs${pidQuery}`).catch(() => {});
    }
    setLines([]);
  }, [name, projectId]);

  return { lines, done, connected, clearLines };
}
