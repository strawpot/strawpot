import { useEffect, useRef, useState } from "react";
import type { TreeData } from "../api/types";

export function useTreeSSE(runId: string): {
  tree: TreeData | null;
  connected: boolean;
} {
  const [tree, setTree] = useState<TreeData | null>(null);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const es = new EventSource(`/api/sessions/${runId}/tree`);
    esRef.current = es;

    es.onopen = () => setConnected(true);

    es.onmessage = (event) => {
      try {
        const data: TreeData = JSON.parse(event.data);
        setTree(data);
      } catch {
        // ignore malformed data
      }
    };

    es.onerror = () => {
      setConnected(false);
      // EventSource auto-reconnects
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [runId]);

  return { tree, connected };
}
