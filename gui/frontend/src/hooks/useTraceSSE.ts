import { useEffect, useRef, useState } from "react";
import type { TraceEvent } from "../api/types";

export function useTraceSSE(
  runId: string,
  active: boolean,
): { events: TraceEvent[]; connected: boolean } {
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const prevRunIdRef = useRef<string>("");
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const backoffMs = useRef(1000);

  useEffect(() => {
    if (!active) return;

    // Only reset events when runId changes
    if (prevRunIdRef.current !== runId) {
      setEvents([]);
      prevRunIdRef.current = runId;
    }

    function connect() {
      const es = new EventSource(`/api/sessions/${runId}/events`);
      esRef.current = es;

      es.onopen = () => {
        setConnected(true);
        backoffMs.current = 1000; // reset on successful connect
      };

      // Named event: full snapshot — replace all events
      es.addEventListener("snapshot", (msg) => {
        try {
          const data = JSON.parse(msg.data);
          if (data.events && Array.isArray(data.events)) {
            setEvents(data.events);
          }
        } catch {
          /* ignore */
        }
      });

      // Named event: incremental delta — append new events
      es.addEventListener("delta", (msg) => {
        try {
          const data = JSON.parse(msg.data);
          if (data.events && Array.isArray(data.events)) {
            setEvents((prev) => [...prev, ...data.events]);
          }
        } catch {
          /* ignore */
        }
      });

      // Backward compat: unnamed events from old server format
      es.onmessage = (msg) => {
        try {
          const data = JSON.parse(msg.data);
          if (data.events && Array.isArray(data.events)) {
            setEvents(data.events);
          }
        } catch {
          /* ignore */
        }
      };

      es.onerror = () => {
        es.close();
        esRef.current = null;
        setConnected(false);
        // Reconnect with exponential backoff
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

  return { events, connected };
}
