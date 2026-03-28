import { Loader2 } from "lucide-react";
import type { AgentActivityDetail } from "@/lib/agent-activity";

/**
 * Displays real-time agent activity: a header line with spinner,
 * plus an optional single child-activity line beneath it.
 *
 * Fixed 2-line footprint: header ("3 agents running") + most-recent child activity.
 */
export function AgentActivityStatus({ detail }: { detail: AgentActivityDetail | null }) {
  return (
    <div className="flex flex-col gap-1 text-muted-foreground">
      <span className="flex items-center gap-2">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        <span className="truncate">{detail?.header ?? "Working…"}</span>
      </span>
      {detail?.childActivity && (
        <span className="ml-5.5 flex items-center gap-1.5 truncate text-xs">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-green-500 animate-pulse" />
          <span className="text-muted-foreground/70">{detail.childActivity}</span>
        </span>
      )}
    </div>
  );
}
