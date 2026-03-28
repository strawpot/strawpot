import { Loader2 } from "lucide-react";
import type { AgentActivityDetail } from "@/lib/agent-activity";

/**
 * Displays real-time agent activity: a header line with spinner,
 * plus optional per-child activity lines beneath it.
 */
export function AgentActivityStatus({ detail }: { detail: AgentActivityDetail | null }) {
  return (
    <div className="flex flex-col gap-1 text-muted-foreground">
      <span className="flex items-center gap-2">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        <span className="truncate">{detail?.header ?? "Working…"}</span>
      </span>
      {(detail?.children.length ?? 0) > 1 && (
        <div className="ml-5.5 flex flex-col gap-0.5 text-xs">
          {detail!.children.map((child) => (
            <span key={child.role} className="flex items-center gap-1.5 truncate">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-green-500 animate-pulse" />
              <span className="font-medium">{child.role}</span>
              <span className="text-muted-foreground/70">{child.activity}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
