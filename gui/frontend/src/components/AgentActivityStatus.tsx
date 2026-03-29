import { Brain, FilePlus, FileText, Loader2, Pencil, Search, Terminal, Users } from "lucide-react";
import type { AgentActivityDetail } from "@/lib/agent-activity";

const ACTIVITY_ICONS: Record<string, typeof Loader2> = {
  Read: FileText,
  Edit: Pencil,
  Write: FilePlus,
  Bash: Terminal,
  Search: Search,
  Agent: Users,
  Think: Brain,
};

function getActivityIcon(action: string | null | undefined): { icon: typeof Loader2; spin: boolean } {
  if (action && action in ACTIVITY_ICONS) {
    return { icon: ACTIVITY_ICONS[action], spin: false };
  }
  return { icon: Loader2, spin: true };
}

/**
 * Displays real-time agent activity: a header line with an activity-specific icon,
 * plus an optional single child-activity line beneath it.
 *
 * Known activity types (Read, Edit, Write, Bash, Search, Agent, Think) show
 * a static icon. Unknown/null falls back to a spinning Loader2.
 */
export function AgentActivityStatus({ detail }: { detail: AgentActivityDetail | null }) {
  const { icon: Icon, spin } = getActivityIcon(detail?.activityAction);
  return (
    <div className="flex flex-col gap-1 text-muted-foreground">
      <span className="flex items-center gap-2">
        <Icon className={`h-3.5 w-3.5${spin ? " animate-spin" : ""}`} />
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
