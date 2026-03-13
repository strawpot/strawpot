import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { queryKeys } from "@/lib/query-keys";

const MAX_TOASTS_PER_WINDOW = 3;
const TOAST_WINDOW_MS = 10_000;
const RECONNECT_SUPPRESS_MS = 2000;

/**
 * Global WebSocket connection for session lifecycle notifications.
 *
 * Replaces the former useGlobalSSE hook, eliminating one HTTP/1.1
 * connection slot per tab.  Same invalidation and toast logic.
 */
export function useGlobalWS(): void {
  const qc = useQueryClient();
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const backoffMs = useRef(1000);
  const connectedAt = useRef(0);
  const toastLog = useRef<Record<string, number[]>>({});
  const isFirstConnect = useRef(true);

  useEffect(() => {
    function shouldToast(eventType: string): boolean {
      const now = Date.now();
      if (now - connectedAt.current < RECONNECT_SUPPRESS_MS) return false;
      const recent = (toastLog.current[eventType] ?? []).filter(
        (t) => now - t < TOAST_WINDOW_MS,
      );
      if (recent.length >= MAX_TOASTS_PER_WINDOW) return false;
      recent.push(now);
      toastLog.current[eventType] = recent;
      return true;
    }

    function handleEvent(data: Record<string, unknown>) {
      const eventType = data.type as string;
      const runIdShort = ((data.run_id as string) ?? "unknown").slice(0, 12);

      // Fire toast notifications
      if (shouldToast(eventType)) {
        if (eventType === "session_started") {
          toast.info(`Session ${runIdShort} started`);
        } else if (eventType === "session_completed") {
          toast.success(`Session ${runIdShort} completed`);
        } else if (eventType === "session_failed") {
          toast.error(`Session ${runIdShort} failed`);
        } else if (eventType === "session_stopped") {
          toast.warning(`Session ${runIdShort} stopped`);
        }
      }

      // Invalidate all session list queries
      qc.invalidateQueries({ queryKey: ["sessions"] });
      if (data.project_id) {
        qc.invalidateQueries({
          queryKey: queryKeys.projects.sessions(data.project_id as number),
        });
        qc.invalidateQueries({
          queryKey: queryKeys.conversations.all(data.project_id as number),
        });
      }
      // Invalidate active conversation detail views
      qc.invalidateQueries({ queryKey: ["conversations", "detail"] });
    }

    function connect() {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${protocol}//${window.location.host}/ws/events`;
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        backoffMs.current = 1000;
        connectedAt.current = Date.now();
        if (!isFirstConnect.current) {
          qc.invalidateQueries({ queryKey: ["sessions"] });
          qc.invalidateQueries({ queryKey: ["conversations"] });
        }
        isFirstConnect.current = false;
      };

      ws.onmessage = (event) => {
        let msg: Record<string, unknown>;
        try {
          msg = JSON.parse(event.data as string) as Record<string, unknown>;
        } catch {
          return;
        }
        // Ignore ping heartbeats
        if (msg.type === "ping") return;
        handleEvent(msg);
      };

      ws.onclose = () => {
        wsRef.current = null;
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
  }, [qc]);
}
