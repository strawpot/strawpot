import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { X } from "lucide-react";
import { toast } from "sonner";
import { useAgentLogSSE } from "@/hooks/useAgentLogSSE";
import { useCancelAgent } from "@/hooks/mutations/use-sessions";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ChevronRight } from "lucide-react";

const TAIL_LINES = 4;
const IDLE_TIMEOUT_MS = 5000;

interface AgentActivityCardProps {
  runId: string;
  projectId: number;
  agentId: string;
  role: string;
  runtime: string;
  startedAt: string;
}

export default function AgentActivityCard({
  runId,
  projectId,
  agentId,
  role,
  runtime,
  startedAt,
}: AgentActivityCardProps) {
  const { lines, done } = useAgentLogSSE(runId, agentId, true);
  const tail = lines.slice(-TAIL_LINES);
  const cancelAgent = useCancelAgent();
  const [confirming, setConfirming] = useState(false);

  // Elapsed time counter
  const [elapsed, setElapsed] = useState("");
  useEffect(() => {
    const start = new Date(startedAt).getTime();
    const update = () => {
      const ms = Date.now() - start;
      const s = Math.floor(ms / 1000) % 60;
      const m = Math.floor(ms / 60000) % 60;
      const h = Math.floor(ms / 3600000);
      setElapsed(h > 0 ? `${h}h ${m}m` : `${m}m ${s}s`);
    };
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
  }, [startedAt]);

  // Idle detection — dim dot after 5s of no new lines
  const lastLineCount = useRef(lines.length);
  const lastActivityTime = useRef(Date.now());
  const [idle, setIdle] = useState(false);

  useEffect(() => {
    if (lines.length !== lastLineCount.current) {
      lastLineCount.current = lines.length;
      lastActivityTime.current = Date.now();
      setIdle(false);
    }
  }, [lines.length]);

  useEffect(() => {
    const id = setInterval(() => {
      if (Date.now() - lastActivityTime.current > IDLE_TIMEOUT_MS) {
        setIdle(true);
      }
    }, 1000);
    return () => clearInterval(id);
  }, []);

  const handleCancel = async () => {
    try {
      await cancelAgent.mutateAsync({ runId, agentId });
      toast.success(`Cancel signal sent for ${role}`);
    } catch (err) {
      toast.error(
        `Failed to cancel agent: ${err instanceof Error ? err.message : "Unknown error"}`,
      );
    }
    setConfirming(false);
  };

  return (
    <Card className="overflow-hidden">
      <CardContent className="space-y-2 pt-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                done
                  ? "bg-muted-foreground"
                  : idle
                    ? "bg-green-300"
                    : "animate-pulse bg-green-500"
              }`}
            />
            <span className="font-medium text-sm">{role}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <Badge variant="outline" className="text-xs">
              {runtime.replace("strawpot-", "")}
            </Badge>
            {!done &&
              (confirming ? (
                <div className="flex gap-1">
                  <Button
                    size="sm"
                    variant="destructive"
                    className="h-5 px-1.5 text-[10px]"
                    onClick={handleCancel}
                    disabled={cancelAgent.isPending}
                  >
                    Confirm
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-5 px-1.5 text-[10px]"
                    onClick={() => setConfirming(false)}
                  >
                    No
                  </Button>
                </div>
              ) : (
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-5 w-5 p-0 text-muted-foreground hover:text-destructive"
                  onClick={() => setConfirming(true)}
                  title="Cancel agent"
                >
                  <X className="h-3 w-3" />
                </Button>
              ))}
          </div>
        </div>

        {/* Session info */}
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <span>Session: {runId.slice(0, 12)}</span>
          <span>&middot;</span>
          <span>{elapsed}</span>
        </div>

        {/* Log tail */}
        <div className="rounded bg-[#1e1e1e] px-2 py-1.5 font-mono text-[11px] leading-[16px] text-[#d4d4d4]">
          {tail.length > 0 ? (
            tail.map((line, i) => (
              <div key={i} className="truncate">
                <span className="text-[#666]">&gt; </span>
                {line}
              </div>
            ))
          ) : (
            <div className="text-[#555]">Waiting for output...</div>
          )}
        </div>

        {/* Link */}
        <div className="flex justify-end">
          <Link
            to={`/projects/${projectId}/sessions/${runId}?tab=logs`}
            className="inline-flex items-center gap-0.5 text-xs text-primary hover:underline"
          >
            View Session
            <ChevronRight className="h-3 w-3" />
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}
