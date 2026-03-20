import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useScheduleRuns } from "@/hooks/queries/use-schedules";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import Pagination from "@/components/Pagination";
import { useRerunScheduleRun } from "@/hooks/mutations/use-schedules";
import { AlertCircle, ExternalLink, RotateCcw } from "lucide-react";
import type { ScheduleRun } from "@/api/types";

function formatDateTime(iso: string | null): string {
  if (!iso) return "\u2014";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return "\u2014";
  }
}

function formatDuration(ms: number | null): string {
  if (ms == null) return "\u2014";
  if (ms < 1000) return `${ms}ms`;
  const secs = Math.round(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  const remSecs = secs % 60;
  return `${mins}m ${remSecs}s`;
}

function StatusBadge({ status }: { status: string }) {
  switch (status) {
    case "completed":
      return <Badge className="bg-emerald-600 hover:bg-emerald-600">Completed</Badge>;
    case "running":
    case "starting":
      return <Badge className="bg-blue-600 hover:bg-blue-600">Running</Badge>;
    case "failed":
      return <Badge variant="destructive">Failed</Badge>;
    default:
      return <Badge variant="secondary">{status}</Badge>;
  }
}

function TypeBadge({ type }: { type: string }) {
  return (
    <Badge variant="outline" className="text-xs">
      {type === "one_time" ? "One-Time" : "Recurring"}
    </Badge>
  );
}

function scheduleLink(r: ScheduleRun): string {
  return r.schedule_type === "one_time"
    ? "/schedules/one-time"
    : "/schedules/recurring";
}

export default function ScheduleRuns() {
  const [page, setPage] = useState(1);
  const { data, isLoading, error } = useScheduleRuns(page);
  const navigate = useNavigate();
  const rerun = useRerunScheduleRun();

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 rounded-lg" />
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex items-center gap-2 text-destructive">
        <AlertCircle className="h-4 w-4" />
        <span>Error: {error.message}</span>
      </div>
    );
  }

  const list = data?.items ?? [];
  const totalPages = data ? Math.ceil(data.total / data.per_page) : 0;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">Run History</h1>

      {data?.total === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed p-12 text-center">
          <p className="text-muted-foreground">No schedule runs yet.</p>
          <p className="text-sm text-muted-foreground mt-1">
            Sessions triggered by schedules will appear here.
          </p>
        </div>
      ) : (
        <>
          <div className="rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Schedule</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Project</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead className="w-[100px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.map((r: ScheduleRun) => (
                  <TableRow key={r.run_id}>
                    <TableCell className="font-medium">
                      <Link
                        to={scheduleLink(r)}
                        className="hover:underline text-foreground"
                      >
                        {r.schedule_name}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <TypeBadge type={r.schedule_type} />
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {r.project_name}
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={r.status} />
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatDateTime(r.started_at)}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatDuration(r.duration_ms)}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          onClick={() => {
                            if (confirm(`Re-run "${r.schedule_name}"?`)) {
                              rerun.mutate(r.run_id);
                            }
                          }}
                          disabled={rerun.isPending}
                          title="Re-run"
                        >
                          <RotateCcw className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8"
                          onClick={() =>
                            navigate(
                              `/projects/${r.project_id}/sessions/${r.run_id}`,
                            )
                          }
                          title="View Session"
                        >
                          <ExternalLink className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <Pagination
            page={page}
            totalPages={totalPages}
            onPageChange={setPage}
          />
        </>
      )}
    </div>
  );
}
