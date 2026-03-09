import { Link } from "react-router-dom";
import type { Session } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

export default function SessionTable({
  sessions,
  projectNames,
}: {
  sessions: Session[];
  projectNames?: Map<number, string>;
}) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Run ID</TableHead>
          {projectNames && <TableHead>Project</TableHead>}
          <TableHead>Role</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Started</TableHead>
          <TableHead>Duration</TableHead>
          <TableHead>Task</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sessions.map((s) => (
          <TableRow key={s.run_id}>
            <TableCell>
              <Link
                to={`/projects/${s.project_id}/sessions/${s.run_id}`}
                className="text-sm font-medium text-primary underline-offset-4 hover:underline"
              >
                {s.run_id.slice(0, 16)}
              </Link>
            </TableCell>
            {projectNames && (
              <TableCell>
                <Link
                  to={`/projects/${s.project_id}`}
                  className="text-sm text-primary underline-offset-4 hover:underline"
                >
                  {projectNames.get(s.project_id) ?? `#${s.project_id}`}
                </Link>
              </TableCell>
            )}
            <TableCell className="text-sm">{s.role}</TableCell>
            <TableCell>
              <StatusBadge status={s.status} />
            </TableCell>
            <TableCell className="text-sm text-muted-foreground">
              {formatTime(s.started_at)}
            </TableCell>
            <TableCell className="text-sm text-muted-foreground">
              {formatDuration(s.duration_ms)}
            </TableCell>
            <TableCell className="max-w-[300px] truncate text-sm">
              {s.task ?? "—"}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function StatusBadge({ status }: { status: string }) {
  const variant = statusVariant(status);
  return (
    <Badge
      variant="outline"
      className={cn(
        "text-xs font-medium",
        variant === "running" &&
          "border-green-200 bg-green-50 text-green-700",
        variant === "success" &&
          "border-green-200 bg-green-50 text-green-700",
        variant === "error" &&
          "border-red-200 bg-red-50 text-red-700",
        variant === "warning" &&
          "border-orange-200 bg-orange-50 text-orange-700",
        variant === "default" &&
          "border-muted bg-muted text-muted-foreground",
      )}
    >
      {status === "running" && (
        <span className="mr-1.5 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-green-500" />
      )}
      {status}
    </Badge>
  );
}

// Alias for backward compatibility with unmigrated pages
export const statusColor = statusVariant;

export function statusVariant(status: string): string {
  switch (status) {
    case "running":
    case "starting":
      return "running";
    case "completed":
      return "success";
    case "failed":
      return "error";
    case "stopped":
      return "warning";
    default:
      return "default";
  }
}

export function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function formatDuration(ms: number | null): string {
  if (ms == null) return "—";
  const secs = Math.round(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  const rem = secs % 60;
  return `${mins}m ${rem}s`;
}
