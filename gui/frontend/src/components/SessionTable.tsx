import { useState } from "react";
import { Link } from "react-router-dom";
import type { Session } from "@/api/types";
import { useDeleteSession } from "@/hooks/mutations/use-sessions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { Trash2 } from "lucide-react";

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
          <TableHead className="w-[80px]" />
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
              {s.user_task ?? s.task ?? "—"}
            </TableCell>
            <TableCell>
              <DeleteSessionButton
                runId={s.run_id}
                disabled={s.status === "starting" || s.status === "running"}
              />
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
          "border-green-200 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950 dark:text-green-400",
        variant === "success" &&
          "border-green-200 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950 dark:text-green-400",
        variant === "error" &&
          "border-red-200 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-400",
        variant === "warning" &&
          "border-orange-200 bg-orange-50 text-orange-700 dark:border-orange-800 dark:bg-orange-950 dark:text-orange-400",
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

function DeleteSessionButton({
  runId,
  disabled,
}: {
  runId: string;
  disabled: boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  const deleteSession = useDeleteSession();

  const handleDelete = async () => {
    try {
      await deleteSession.mutateAsync(runId);
    } catch {
      // error state handled by mutation
    }
  };

  if (confirming) {
    return (
      <div className="flex gap-1">
        <Button
          size="sm"
          variant="destructive"
          onClick={handleDelete}
          disabled={deleteSession.isPending}
        >
          Confirm
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setConfirming(false)}
        >
          No
        </Button>
      </div>
    );
  }

  return (
    <Button
      size="sm"
      variant="ghost"
      className="text-muted-foreground hover:text-destructive"
      onClick={() => setConfirming(true)}
      disabled={disabled}
    >
      <Trash2 className="h-4 w-4" />
    </Button>
  );
}
