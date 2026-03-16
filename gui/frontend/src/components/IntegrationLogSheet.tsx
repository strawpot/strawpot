import { useCallback, useEffect, useRef, useState } from "react";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ArrowDown, Search } from "lucide-react";
import { useIntegrationLogWS } from "@/hooks/useIntegrationLogWS";

const LINE_HEIGHT = 18;
const OVERSCAN = 10;

interface IntegrationLogSheetProps {
  name: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export default function IntegrationLogSheet({
  name,
  open,
  onOpenChange,
}: IntegrationLogSheetProps) {
  // Only connect when sheet is open
  const activeName = open ? name : null;
  const { lines, done, connected } = useIntegrationLogWS(activeName);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-[700px] sm:max-w-[700px]">
        <SheetHeader>
          <SheetTitle>Logs: {name}</SheetTitle>
          <SheetDescription>
            Adapter stdout/stderr output
          </SheetDescription>
        </SheetHeader>
        <div className="mt-4">
          <LogTerminal
            lines={lines}
            done={done}
            connected={connected}
          />
        </div>
      </SheetContent>
    </Sheet>
  );
}

function LogTerminal({
  lines,
  done,
  connected,
}: {
  lines: string[];
  done: boolean;
  connected: boolean;
}) {
  const [search, setSearch] = useState("");
  const lowerSearch = search.toLowerCase();
  const matchIndices = search
    ? lines.reduce<number[]>((acc, line, i) => {
        if (line.toLowerCase().includes(lowerSearch)) acc.push(i);
        return acc;
      }, [])
    : [];

  const containerRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [containerHeight, setContainerHeight] = useState(0);
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
    const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - LINE_HEIGHT * 2;
    setAutoScroll(atBottom);
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (el) setContainerHeight(el.clientHeight);
  }, []);

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

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <div className="relative">
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
        <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
          {done ? (
            "Stream ended"
          ) : (
            <>
              <span
                className={`inline-block h-1.5 w-1.5 rounded-full ${
                  connected ? "animate-pulse bg-green-500" : "bg-orange-400"
                }`}
              />
              {connected ? "Live" : "Connecting..."}
            </>
          )}
        </span>
      </div>

      <div className="relative">
        <div
          ref={containerRef}
          className="h-[500px] overflow-auto rounded-md bg-[#1e1e1e] font-mono text-xs text-[#d4d4d4]"
          onScroll={handleScroll}
        >
          {lines.length === 0 ? (
            <div className="flex h-full items-center justify-center text-[#666]">
              {!done ? "Waiting for log output..." : "No log output."}
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
                  const isMatch = search && line.toLowerCase().includes(lowerSearch);
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
                      <span>{line}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>

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
