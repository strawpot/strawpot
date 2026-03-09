import { useEffect, useRef, useState } from "react";

const MAX_LINES = 10_000;

export interface UseAgentLogSSEResult {
  lines: string[];
  connected: boolean;
  done: boolean;
}

export function useAgentLogSSE(
  runId: string,
  agentId: string,
  active: boolean,
): UseAgentLogSSEResult {
  const [lines, setLines] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
  const [done, setDone] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const backoffMs = useRef(1000);
  const prevKeyRef = useRef("");

  useEffect(() => {
    if (!active || !agentId) return;

    const key = `${runId}:${agentId}`;
    if (prevKeyRef.current !== key) {
      setLines([]);
      setDone(false);
      prevKeyRef.current = key;
    }

    function connect() {
      const es = new EventSource(
        `/api/sessions/${runId}/logs/${agentId}`,
      );
      esRef.current = es;

      es.onopen = () => {
        setConnected(true);
        backoffMs.current = 1000;
      };

      es.addEventListener("snapshot", (msg) => {
        try {
          const data = JSON.parse(msg.data);
          if (Array.isArray(data.lines)) {
            setLines(data.lines.slice(-MAX_LINES));
          }
        } catch {
          /* ignore */
        }
      });

      es.addEventListener("append", (msg) => {
        try {
          const data = JSON.parse(msg.data);
          if (Array.isArray(data.lines) && data.lines.length > 0) {
            setLines((prev) => {
              const merged = [...prev, ...data.lines];
              return merged.length > MAX_LINES
                ? merged.slice(-MAX_LINES)
                : merged;
            });
          }
        } catch {
          /* ignore */
        }
      });

      es.addEventListener("done", () => {
        setDone(true);
        es.close();
        esRef.current = null;
      });

      es.onerror = () => {
        es.close();
        esRef.current = null;
        setConnected(false);
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
  }, [runId, agentId, active]);

  return { lines, connected, done };
}
