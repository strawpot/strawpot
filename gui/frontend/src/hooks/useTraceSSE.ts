import { useEffect, useRef, useState } from "react";
import type { TraceEvent } from "../api/types";

export function useTraceSSE(
  runId: string,
  active: boolean,
): { events: TraceEvent[]; connected: boolean } {
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!active) return;

    const es = new EventSource(`/api/sessions/${runId}/events`);
    esRef.current = es;

    es.onopen = () => setConnected(true);

    es.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data);
        if (data.events && Array.isArray(data.events)) {
          setEvents((prev) => [...prev, ...data.events]);
        }
      } catch {
        // ignore malformed data
      }
    };

    es.onerror = () => {
      setConnected(false);
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [runId, active]);

  return { events, connected };
}
