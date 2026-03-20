import { useState } from "react";
import cronstrue from "cronstrue";
import { cronUtcToLocal } from "@/lib/utils";
import { useSchedules } from "@/hooks/queries/use-schedules";
import { useDeleteSchedule, useToggleSchedule, useTriggerSchedule } from "@/hooks/mutations/use-schedules";
import CreateScheduleDialog from "@/components/CreateScheduleDialog";
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { AlertCircle, Pause, Pencil, Play, Plus, Trash2, Zap } from "lucide-react";
import type { Schedule } from "@/api/types";

function cronToLocalDesc(cron: string | null): string {
  if (!cron) return "—";
  try {
    return cronstrue.toString(cronUtcToLocal(cron));
  } catch {
    return cron;
  }
}

function formatRelative(iso: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    const now = new Date();
    const diffMs = d.getTime() - now.getTime();
    const absDiff = Math.abs(diffMs);
    if (absDiff < 60_000) return diffMs > 0 ? "in < 1m" : "< 1m ago";
    if (absDiff < 3_600_000) {
      const mins = Math.round(absDiff / 60_000);
      return diffMs > 0 ? `in ${mins}m` : `${mins}m ago`;
    }
    if (absDiff < 86_400_000) {
      const hours = Math.round(absDiff / 3_600_000);
      return diffMs > 0 ? `in ${hours}h` : `${hours}h ago`;
    }
    return d.toLocaleDateString();
  } catch {
    return "—";
  }
}

function formatLocalDateTime(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      weekday: "short", month: "short", day: "numeric",
      hour: "numeric", minute: "2-digit",
    });
  } catch {
    return "—";
  }
}

function StatusBadge({ schedule }: { schedule: Schedule }) {
  if (!schedule.enabled) {
    return <Badge variant="secondary">Disabled</Badge>;
  }
  if (schedule.last_error) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger>
            <Badge variant="destructive">Error</Badge>
          </TooltipTrigger>
          <TooltipContent className="max-w-xs">
            <p className="text-xs">{schedule.last_error}</p>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }
  return <Badge className="bg-emerald-600 hover:bg-emerald-600">Active</Badge>;
}

export default function ScheduledTasks() {
  const { data: schedules, isLoading, error } = useSchedules("recurring");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Schedule | null>(null);
  const deleteSchedule = useDeleteSchedule();
  const toggleSchedule = useToggleSchedule();
  const triggerSchedule = useTriggerSchedule();

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

  const list = schedules ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Recurring Schedules</h1>
        <Button onClick={() => { setEditing(null); setDialogOpen(true); }}>
          <Plus className="mr-2 h-4 w-4" />
          Create Schedule
        </Button>
      </div>

      {list.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed p-12 text-center">
          <p className="text-muted-foreground">No recurring schedules yet.</p>
          <Button
            variant="outline"
            className="mt-4"
            onClick={() => { setEditing(null); setDialogOpen(true); }}
          >
            <Plus className="mr-2 h-4 w-4" />
            Create your first schedule
          </Button>
        </div>
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Project</TableHead>
                <TableHead>Schedule</TableHead>
                <TableHead>Next Run</TableHead>
                <TableHead>Last Run</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-[120px]">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="font-medium">{s.name}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {s.project_name}
                  </TableCell>
                  <TableCell className="text-sm">
                    {cronToLocalDesc(s.cron_expr)}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    <span>{formatLocalDateTime(s.next_run_at)}</span>
                    <span className="ml-1 text-xs opacity-60">({formatRelative(s.next_run_at)})</span>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {formatRelative(s.last_run_at)}
                  </TableCell>
                  <TableCell>
                    <StatusBadge schedule={s} />
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        onClick={() => triggerSchedule.mutate(s.id)}
                        disabled={triggerSchedule.isPending}
                        title="Run Now"
                      >
                        <Zap className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        onClick={() => {
                          setEditing(s);
                          setDialogOpen(true);
                        }}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        onClick={() =>
                          toggleSchedule.mutate({
                            id: s.id,
                            enable: !s.enabled,
                          })
                        }
                      >
                        {s.enabled ? (
                          <Pause className="h-3.5 w-3.5" />
                        ) : (
                          <Play className="h-3.5 w-3.5" />
                        )}
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 text-destructive hover:text-destructive"
                        onClick={() => {
                          if (confirm(`Delete schedule "${s.name}"?`)) {
                            deleteSchedule.mutate(s.id);
                          }
                        }}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <CreateScheduleDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        editing={editing}
      />
    </div>
  );
}
