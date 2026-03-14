import { useState } from "react";
import { useSchedules } from "@/hooks/queries/use-schedules";
import { useDeleteSchedule, useToggleSchedule } from "@/hooks/mutations/use-schedules";
import CreateOneTimeScheduleDialog from "@/components/CreateOneTimeScheduleDialog";
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
import { AlertCircle, Pause, Play, Plus, Trash2 } from "lucide-react";
import type { Schedule } from "@/api/types";

function formatDateTime(iso: string | null): string {
  if (!iso) return "\u2014";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return "\u2014";
  }
}

function StatusBadge({ schedule }: { schedule: Schedule }) {
  if (!schedule.enabled && schedule.last_run_at) {
    return <Badge variant="secondary">Fired</Badge>;
  }
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
  return <Badge className="bg-emerald-600 hover:bg-emerald-600">Pending</Badge>;
}

export default function OneTimeSchedules() {
  const { data: schedules, isLoading, error } = useSchedules("one_time");
  const [dialogOpen, setDialogOpen] = useState(false);
  const deleteSchedule = useDeleteSchedule();
  const toggleSchedule = useToggleSchedule();

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
        <h1 className="text-2xl font-bold tracking-tight">One-Time Schedules</h1>
        <Button onClick={() => setDialogOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          Create One-Time Schedule
        </Button>
      </div>

      {list.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed p-12 text-center">
          <p className="text-muted-foreground">No one-time schedules yet.</p>
          <Button
            variant="outline"
            className="mt-4"
            onClick={() => setDialogOpen(true)}
          >
            <Plus className="mr-2 h-4 w-4" />
            Create your first one-time schedule
          </Button>
        </div>
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Project</TableHead>
                <TableHead>Scheduled For</TableHead>
                <TableHead>Last Run</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-[100px]">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {list.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="font-medium">{s.name}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {s.project_name}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {formatDateTime(s.run_at)}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {formatDateTime(s.last_run_at)}
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

      <CreateOneTimeScheduleDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
      />
    </div>
  );
}
