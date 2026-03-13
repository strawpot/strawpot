import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ArrowDown, Download, Search } from "lucide-react";
import type { AgentInfo } from "@/api/types";
import type { AgentLogState } from "@/hooks/useSessionWS";

const LINE_HEIGHT = 18;
const OVERSCAN = 10;

interface AgentLogViewerProps {
  runId: string;
  agents: Record<string, AgentInfo>;
  active: boolean;
  agentLogs: Map<string, AgentLogState>;
  wsConnected: boolean;
  subscribeLogs: (agentId: string, offset?: number) => void;
  unsubscribeLogs: (agentId: string) => void;
}

export default function AgentLogViewer({
  runId,
  agents,
  active,
  agentLogs,
  wsConnected,
  subscribeLogs,
  unsubscribeLogs,
}: AgentLogViewerProps) {
  const agentIds = Object.keys(agents);
  const rootId = agentIds.find((id) => agents[id].parent === null) ?? agentIds[0] ?? "";
  const [selectedAgent, setSelectedAgent] = useState(rootId);

  // Subscribe/unsubscribe to agent logs via WS
  useEffect(() => {
    if (!selectedAgent || !wsConnected) return;
    subscribeLogs(selectedAgent);
    return () => {
      unsubscribeLogs(selectedAgent);
    };
  }, [selectedAgent, wsConnected, subscribeLogs, unsubscribeLogs]);

  const logState = agentLogs.get(selectedAgent);
  const lines = logState?.lines ?? [];
  const done = logState?.done ?? false;
  const connected = wsConnected;

  // Search
  const [search, setSearch] = useState("");
  const lowerSearch = search.toLowerCase();
  const matchIndices = search
    ? lines.reduce<number[]>((acc, line, i) => {
        if (line.toLowerCase().includes(lowerSearch)) acc.push(i);
        return acc;
      }, [])
    : [];

  // Virtual scrolling
  const containerRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [containerHeight, setContainerHeight] = useState(0);

  // Auto-scroll
  const [autoScroll, setAutoScroll] = useState(true);
  const prevLineCount = useRef(0);

  const totalHeight = lines.length * LINE_HEIGHT;
  const startIndex = Math.max(0, Math.floor(scrollTop / LINE_HEIGHT) - OVERSCAN);
  const visibleCount = Math.ceil(containerHeight / LINE_HEIGHT) + OVERSCAN * 2;
  const endIndex = Math.min(lines.length, startIndex + visibleCount);
  const visibleLines = lines.slice(startIndex, endIndex);
  const gutterWidth = String(lines.length).length;

  const handleScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    setScrollTop(el.scrollTop);
    setContainerHeight(el.clientHeight);

    // Disable auto-scroll if user scrolled away from bottom
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - LINE_HEIGHT * 2;
    setAutoScroll(atBottom);
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    setContainerHeight(el.clientHeight);
  }, []);

  // Auto-scroll on new lines
  useEffect(() => {
    if (autoScroll && lines.length > prevLineCount.current) {
      const el = containerRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    }
    prevLineCount.current = lines.length;
  }, [lines.length, autoScroll]);

  const jumpToBottom = () => {
    const el = containerRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
      setAutoScroll(true);
    }
  };

  const handleDownload = async () => {
    try {
      const res = await fetch(
        `/api/sessions/${runId}/logs/${selectedAgent}/full`,
      );
      if (!res.ok) return;
      const text = await res.text();
      const blob = new Blob([text], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${selectedAgent}.log`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="space-y-3">
      {/* Toolbar */}
      <div className="flex items-center gap-2">
        {agentIds.length > 1 && (
          <Select value={selectedAgent} onValueChange={setSelectedAgent}>
            <SelectTrigger className="w-[220px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {agentIds.map((id) => (
                <SelectItem key={id} value={id}>
                  {agents[id].role} ({id.slice(0, 8)})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        {agentIds.length === 1 && (
          <span className="text-sm text-muted-foreground">
            {agents[selectedAgent]?.role} ({selectedAgent.slice(0, 8)})
          </span>
        )}

        <div className="relative ml-auto">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="h-8 w-[200px] pl-7 text-xs"
            placeholder="Search logs..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        {search && (
          <span className="text-xs text-muted-foreground">
            {matchIndices.length} match{matchIndices.length !== 1 ? "es" : ""}
          </span>
        )}

        <Button variant="outline" size="sm" onClick={handleDownload}>
          <Download className="mr-1 h-3.5 w-3.5" />
          Download
        </Button>

        <StatusIndicator connected={connected} done={done} active={active} />
      </div>

      {/* Terminal */}
      <div className="relative">
        <div
          ref={containerRef}
          className="h-[500px] overflow-auto rounded-md bg-[#1e1e1e] font-mono text-xs text-[#d4d4d4]"
          onScroll={handleScroll}
        >
          {lines.length === 0 ? (
            <div className="flex h-full items-center justify-center text-[#666]">
              {active && !done ? "Waiting for log output..." : "No log output."}
            </div>
          ) : (
            <div style={{ height: totalHeight, position: "relative" }}>
              <div
                style={{
                  position: "absolute",
                  top: startIndex * LINE_HEIGHT,
                  left: 0,
                  right: 0,
                }}
              >
                {visibleLines.map((line, i) => {
                  const lineNum = startIndex + i;
                  const isMatch =
                    search && line.toLowerCase().includes(lowerSearch);
                  return (
                    <div
                      key={lineNum}
                      className={isMatch ? "bg-yellow-900/30" : undefined}
                      style={{
                        height: LINE_HEIGHT,
                        lineHeight: `${LINE_HEIGHT}px`,
                        display: "flex",
                        whiteSpace: "pre",
                      }}
                    >
                      <span
                        className="select-none text-right text-[#555]"
                        style={{
                          width: `${(gutterWidth + 2) * 0.6}em`,
                          paddingRight: "1em",
                          flexShrink: 0,
                        }}
                      >
                        {lineNum + 1}
                      </span>
                      <span>
                        {isMatch ? (
                          <HighlightedLine line={line} search={lowerSearch} />
                        ) : (
                          line
                        )}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Jump to bottom button */}
        {!autoScroll && lines.length > 0 && (
          <Button
            size="sm"
            variant="secondary"
            className="absolute bottom-3 right-4 shadow-md"
            onClick={jumpToBottom}
          >
            <ArrowDown className="mr-1 h-3.5 w-3.5" />
            Jump to bottom
          </Button>
        )}
      </div>
    </div>
  );
}

function StatusIndicator({
  connected,
  done,
  active,
}: {
  connected: boolean;
  done: boolean;
  active: boolean;
}) {
  if (done || !active) {
    return (
      <span className="text-xs text-muted-foreground">
        Session ended
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-xs text-muted-foreground">
      <span
        className={`inline-block h-1.5 w-1.5 rounded-full ${
          connected ? "animate-pulse bg-green-500" : "bg-orange-400"
        }`}
      />
      {connected ? "Live" : "Connecting..."}
    </span>
  );
}

function HighlightedLine({
  line,
  search,
}: {
  line: string;
  search: string;
}) {
  const parts: React.ReactNode[] = [];
  const lower = line.toLowerCase();
  let lastIndex = 0;
  let idx = lower.indexOf(search, lastIndex);
  let key = 0;

  while (idx !== -1) {
    if (idx > lastIndex) {
      parts.push(line.slice(lastIndex, idx));
    }
    parts.push(
      <span key={key++} className="bg-yellow-500/60 text-white">
        {line.slice(idx, idx + search.length)}
      </span>,
    );
    lastIndex = idx + search.length;
    idx = lower.indexOf(search, lastIndex);
  }
  if (lastIndex < line.length) {
    parts.push(line.slice(lastIndex));
  }
  return <>{parts}</>;
}
