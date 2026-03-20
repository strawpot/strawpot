import { useEffect, useMemo, useState } from "react";
import cronstrue from "cronstrue";
import { cronLocalToUtc, cronUtcToLocal } from "@/lib/utils";
import { useProjects } from "@/hooks/queries/use-projects";
import { useProjectResources } from "@/hooks/queries/use-project-resources";
import { useProjectConversations, useImuConversations } from "@/hooks/queries/use-conversations";
import { useCreateConversation, useCreateImuConversation } from "@/hooks/mutations/use-conversations";
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
  { label: "Weekdays at 10am", value: "0 10 * * 1-5" },
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
  const createConversation = useCreateConversation();
  const createImuConversation = useCreateImuConversation();

  const [name, setName] = useState("");
  const [projectId, setProjectId] = useState<string>("");
  const [task, setTask] = useState("");
  const [cronExpr, setCronExpr] = useState("");
  const [role, setRole] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [skipIfRunning, setSkipIfRunning] = useState(true);
  const [conversationId, setConversationId] = useState<string>("none");
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const selectedProjectId = editing ? editing.project_id : (projectId ? Number(projectId) : -1);
  const isImu = selectedProjectId === 0;
  const { data: projectResources } = useProjectResources(selectedProjectId);
  const { data: projectConversations } = useProjectConversations(selectedProjectId);
  const { data: imuConversations } = useImuConversations();
  const conversationItems = useMemo(() => {
    if (selectedProjectId === 0) {
      return (imuConversations ?? []).map((c) => ({ id: c.id, title: c.title }));
    }
    return (projectConversations?.items ?? []).map((c) => ({ id: c.id, title: c.title }));
  }, [selectedProjectId, projectConversations, imuConversations]);
  const roles = useMemo(
    () =>
      (projectResources ?? [])
        .filter((r) => r.type === "roles")
        .map((r) => r.name),
    [projectResources],
  );
  useEffect(() => {
    if (isImu) setRole("imu");
    else setRole("");
  }, [isImu]);

  useEffect(() => {
    if (open && editing) {
      setName(editing.name);
      setProjectId(String(editing.project_id));
      setTask(editing.task);
      setCronExpr(editing.cron_expr ? cronUtcToLocal(editing.cron_expr) : "");
      setRole(editing.role ?? "");
      setSystemPrompt(editing.system_prompt ?? "");
      setSkipIfRunning(editing.skip_if_running);
      setConversationId(editing.conversation_id ? String(editing.conversation_id) : "none");
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
    setConversationId("none");
    setAdvancedOpen(false);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    try {
      let resolvedConvId: number | null = null;
      const pid = editing ? editing.project_id : Number(projectId);
      if (conversationId === "new") {
        if (pid === 0) {
          const conv = await createImuConversation.mutateAsync();
          resolvedConvId = conv.id;
        } else {
          const conv = await createConversation.mutateAsync({
            project_id: pid,
            title: name.trim() || undefined,
          });
          resolvedConvId = conv.id;
        }
      } else if (conversationId !== "none") {
        resolvedConvId = Number(conversationId);
      }

      const body = {
        name: name.trim(),
        task: task.trim(),
        cron_expr: cronLocalToUtc(cronExpr.trim()),
        role: role.trim() || undefined,
        system_prompt: systemPrompt.trim() || undefined,
        skip_if_running: skipIfRunning,
        conversation_id: resolvedConvId,
      };
      if (editing) {
        await updateSchedule.mutateAsync({ id: editing.id, ...body });
      } else {
        await createSchedule.mutateAsync({
          ...body,
          project_id: pid,
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

  const isPending = createSchedule.isPending || updateSchedule.isPending || createConversation.isPending || createImuConversation.isPending;
  const mutationError = createSchedule.error || updateSchedule.error;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg max-h-[90vh] overflow-y-auto">
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
                  <SelectItem value="0">Imu</SelectItem>
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
              disabled={isImu}
            />
            <datalist id="sched-role-list">
              {roles.map((r) => (
                <option key={r} value={r} />
              ))}
            </datalist>
            {!isImu && role.trim() && roles.length > 0 && !roles.includes(role.trim()) && (
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

          <div className="space-y-2">
            <Label htmlFor="sched-conversation">Conversation</Label>
            <Select value={conversationId} onValueChange={setConversationId}>
              <SelectTrigger id="sched-conversation">
                <SelectValue placeholder="No conversation" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">No conversation</SelectItem>
                <SelectItem value="new">Create new conversation</SelectItem>
                {conversationItems.map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>
                    {c.title || `Conversation #${c.id}`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {conversationId === "none"
                ? "Each run starts a standalone session."
                : conversationId === "new"
                  ? "A new conversation will be created — all runs share it."
                  : "All runs continue this conversation's context."}
            </p>
          </div>

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
