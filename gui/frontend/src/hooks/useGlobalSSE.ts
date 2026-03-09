import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/query-keys";

/**
 * Connect to the global SSE event bus and invalidate TanStack Query
 * caches when session lifecycle events arrive.
 */
export function useGlobalSSE(): void {
  const qc = useQueryClient();
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const backoffMs = useRef(1000);

  useEffect(() => {
    function connect() {
      const es = new EventSource("/api/events");
      esRef.current = es;

      es.onopen = () => {
        backoffMs.current = 1000; // reset on successful connect
      };

      const handleLifecycle = (e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data);
          // Invalidate all session list queries
          qc.invalidateQueries({ queryKey: ["sessions"] });
          // Invalidate specific project sessions if project_id present
          if (data.project_id) {
            qc.invalidateQueries({
              queryKey: queryKeys.projects.sessions(data.project_id),
            });
          }
        } catch {
          /* ignore */
        }
      };

      es.addEventListener("session_started", handleLifecycle);
      es.addEventListener("session_completed", handleLifecycle);
      es.addEventListener("session_failed", handleLifecycle);
      es.addEventListener("session_stopped", handleLifecycle);

      es.onerror = () => {
        es.close();
        esRef.current = null;
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
  }, [qc]);
}
