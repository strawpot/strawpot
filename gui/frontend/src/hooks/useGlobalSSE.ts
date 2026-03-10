import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { queryKeys } from "@/lib/query-keys";

const MAX_TOASTS_PER_WINDOW = 3;
const TOAST_WINDOW_MS = 10_000;
const RECONNECT_SUPPRESS_MS = 2000;

/**
 * Connect to the global SSE event bus, invalidate TanStack Query
 * caches, and fire toast notifications on session lifecycle events.
 */
export function useGlobalSSE(): void {
  const qc = useQueryClient();
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const backoffMs = useRef(1000);
  const connectedAt = useRef(0);
  const toastLog = useRef<Record<string, number[]>>({});

  useEffect(() => {
    function shouldToast(eventType: string): boolean {
      const now = Date.now();
      // Suppress toasts right after (re)connect to avoid stale flood
      if (now - connectedAt.current < RECONNECT_SUPPRESS_MS) return false;
      // Rate limit: max N per event type within window
      const recent = (toastLog.current[eventType] ?? []).filter(
        (t) => now - t < TOAST_WINDOW_MS,
      );
      if (recent.length >= MAX_TOASTS_PER_WINDOW) return false;
      recent.push(now);
      toastLog.current[eventType] = recent;
      return true;
    }

    function connect() {
      const es = new EventSource("/api/events");
      esRef.current = es;

      es.onopen = () => {
        backoffMs.current = 1000;
        connectedAt.current = Date.now();
      };

      const handleLifecycle = (e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data);
          const runIdShort = (data.run_id ?? "unknown").slice(0, 12);

          // Fire toast notifications
          if (shouldToast(e.type)) {
            if (e.type === "session_started") {
              toast.info(`Session ${runIdShort} started`);
            } else if (e.type === "session_completed") {
              toast.success(`Session ${runIdShort} completed`);
            } else if (e.type === "session_failed") {
              toast.error(`Session ${runIdShort} failed`);
            } else if (e.type === "session_stopped") {
              toast.warning(`Session ${runIdShort} stopped`);
            }
          }

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
