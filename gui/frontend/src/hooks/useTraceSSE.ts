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

  useEffect(() => {
    if (!active) return;

    // Only reset events when runId changes
    if (prevRunIdRef.current !== runId) {
      setEvents([]);
      prevRunIdRef.current = runId;
    }

    const es = new EventSource(`/api/sessions/${runId}/events`);
    esRef.current = es;

    es.onopen = () => setConnected(true);

    es.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data);
        if (data.events && Array.isArray(data.events)) {
          // Backend sends full snapshot each time — replace, don't append
          setEvents(data.events);
        }
      } catch {
        // ignore malformed data
      }
    };

    es.onerror = () => {
      // Server closed the stream (session ended) — stop reconnecting
      es.close();
      esRef.current = null;
      setConnected(false);
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [runId, active]);

  return { events, connected };
}
