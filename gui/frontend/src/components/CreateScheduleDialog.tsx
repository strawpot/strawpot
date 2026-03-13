import { useEffect, useMemo, useState } from "react";
import cronstrue from "cronstrue";
import { useProjects } from "@/hooks/queries/use-projects";
import { useProjectResources } from "@/hooks/queries/use-project-resources";
import { useCreateSchedule, useUpdateSchedule } from "@/hooks/mutations/use-schedules";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { ChevronDown } from "lucide-react";
import type { Schedule } from "@/api/types";

const CRON_PRESETS = [
  { label: "Every 1 minute", value: "* * * * *" },
  { label: "Every 5 minutes", value: "*/5 * * * *" },
  { label: "Every hour", value: "0 * * * *" },
  { label: "Daily at midnight", value: "0 0 * * *" },
  { label: "Weekdays at 9am", value: "0 9 * * 1-5" },
  { label: "Weekly Monday 9am", value: "0 9 * * 1" },
];

interface CreateScheduleDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editing: Schedule | null;
}

export default function CreateScheduleDialog({
  open,
  onOpenChange,
  editing,
}: CreateScheduleDialogProps) {
  const { data: projects } = useProjects();
  const createSchedule = useCreateSchedule();
  const updateSchedule = useUpdateSchedule();

  const [name, setName] = useState("");
  const [projectId, setProjectId] = useState<string>("");
  const [task, setTask] = useState("");
  const [cronExpr, setCronExpr] = useState("");
  const [role, setRole] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [skipIfRunning, setSkipIfRunning] = useState(true);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const selectedProjectId = editing ? editing.project_id : Number(projectId) || 0;
  const { data: projectResources } = useProjectResources(selectedProjectId);
  const roles = useMemo(
    () =>
      (projectResources ?? [])
        .filter((r) => r.type === "roles")
        .map((r) => r.name),
    [projectResources],
  );

  useEffect(() => {
    if (open && editing) {
      setName(editing.name);
      setProjectId(String(editing.project_id));
      setTask(editing.task);
      setCronExpr(editing.cron_expr);
      setRole(editing.role ?? "");
      setSystemPrompt(editing.system_prompt ?? "");
      setSkipIfRunning(editing.skip_if_running);
    } else if (open && !editing) {
      resetForm();
    }
  }, [open, editing]);

  function resetForm() {
    setName("");
    setProjectId("");
    setTask("");
    setCronExpr("");
    setRole("");
    setSystemPrompt("");
    setSkipIfRunning(true);
    setAdvancedOpen(false);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    try {
      const body = {
        name: name.trim(),
        task: task.trim(),
        cron_expr: cronExpr.trim(),
        role: role.trim() || undefined,
        system_prompt: systemPrompt.trim() || undefined,
        skip_if_running: skipIfRunning,
      };
      if (editing) {
        await updateSchedule.mutateAsync({ id: editing.id, ...body });
      } else {
        await createSchedule.mutateAsync({
          ...body,
          project_id: Number(projectId),
        });
      }
      resetForm();
      onOpenChange(false);
    } catch {
      // error displayed via mutation state
    }
  }

  const cronDescription = useMemo(() => {
    if (!cronExpr.trim()) return null;
    try {
      return cronstrue.toString(cronExpr.trim());
    } catch {
      return null;
    }
  }, [cronExpr]);

  const isPending = createSchedule.isPending || updateSchedule.isPending;
  const mutationError = createSchedule.error || updateSchedule.error;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {editing ? "Edit Schedule" : "Create Schedule"}
          </DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="sched-name">
              Name <span className="text-destructive">*</span>
            </Label>
            <Input
              id="sched-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. github-issue-checker"
              required
              autoFocus
            />
          </div>

          {!editing && (
            <div className="space-y-2">
              <Label htmlFor="sched-project">
                Project <span className="text-destructive">*</span>
              </Label>
              <Select value={projectId} onValueChange={setProjectId} required>
                <SelectTrigger id="sched-project">
                  <SelectValue placeholder="Select a project" />
                </SelectTrigger>
                <SelectContent>
                  {(projects ?? []).map((p) => (
                    <SelectItem key={p.id} value={String(p.id)}>
                      {p.display_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="sched-task">
              Task <span className="text-destructive">*</span>
            </Label>
            <Textarea
              id="sched-task"
              value={task}
              onChange={(e) => setTask(e.target.value)}
              placeholder="What should the agent do each time this runs?"
              required
              rows={3}
            />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="sched-cron">
                Cron Expression <span className="text-destructive">*</span>
              </Label>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="sm" className="h-6 text-xs">
                    Presets
                    <ChevronDown className="ml-1 h-3 w-3" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  {CRON_PRESETS.map((p) => (
                    <DropdownMenuItem
                      key={p.value}
                      onClick={() => setCronExpr(p.value)}
                    >
                      <span className="mr-3 font-mono text-xs text-muted-foreground">
                        {p.value}
                      </span>
                      {p.label}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
            <Input
              id="sched-cron"
              value={cronExpr}
              onChange={(e) => setCronExpr(e.target.value)}
              placeholder="*/5 * * * *"
              required
              className="font-mono"
            />
            {cronDescription && (
              <p className="text-xs text-muted-foreground">{cronDescription}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="sched-role">Role</Label>
            <Input
              id="sched-role"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              placeholder={roles[0] ?? "orchestrator"}
              list="sched-role-list"
            />
            <datalist id="sched-role-list">
              {roles.map((r) => (
                <option key={r} value={r} />
              ))}
            </datalist>
            {role.trim() && roles.length > 0 && !roles.includes(role.trim()) && (
              <p className="text-xs text-destructive">Role not found in installed roles</p>
            )}
          </div>

          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={skipIfRunning}
              onChange={(e) => setSkipIfRunning(e.target.checked)}
              className="rounded border-input"
            />
            <span className="text-sm">
              Skip if already running
            </span>
            <span className="text-xs text-muted-foreground">
              — don't start a new session while a previous one is still active
            </span>
          </label>

          <Collapsible open={advancedOpen} onOpenChange={setAdvancedOpen}>
            <CollapsibleTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="flex items-center gap-1 px-0 text-xs text-muted-foreground"
              >
                <ChevronDown
                  className={`h-3 w-3 transition-transform ${advancedOpen ? "rotate-180" : ""}`}
                />
                Advanced Options
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="space-y-4 pt-2">
              <div className="space-y-2">
                <Label htmlFor="sched-prompt">System Prompt</Label>
                <Textarea
                  id="sched-prompt"
                  value={systemPrompt}
                  onChange={(e) => setSystemPrompt(e.target.value)}
                  placeholder="Additional instructions for the agent..."
                  rows={3}
                />
              </div>
            </CollapsibleContent>
          </Collapsible>

          {mutationError && (
            <p className="text-sm text-destructive">
              {(mutationError as Error).message}
            </p>
          )}

          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isPending || (!!role.trim() && roles.length > 0 && !roles.includes(role.trim()))}>
              {isPending
                ? "Saving..."
                : editing
                  ? "Update"
                  : "Create"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
