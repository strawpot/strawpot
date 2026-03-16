import { useEffect, useMemo, useState } from "react";
import { useProjects } from "@/hooks/queries/use-projects";
import { useProjectResources } from "@/hooks/queries/use-project-resources";
import { useProjectConversations, useImuConversations } from "@/hooks/queries/use-conversations";
import { useCreateConversation, useCreateImuConversation } from "@/hooks/mutations/use-conversations";
import { useCreateOneTimeSchedule } from "@/hooks/mutations/use-schedules";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export default function CreateOneTimeScheduleDialog({
  open,
  onOpenChange,
}: Props) {
  const { data: projects } = useProjects();
  const createSchedule = useCreateOneTimeSchedule();
  const createConversation = useCreateConversation();
  const createImuConversation = useCreateImuConversation();

  const [name, setName] = useState("");
  const [projectId, setProjectId] = useState<string>("");
  const [task, setTask] = useState("");
  const [runAt, setRunAt] = useState("");
  const [role, setRole] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [conversationId, setConversationId] = useState<string>("none");
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const selectedProjectId = projectId ? Number(projectId) : -1;
  const isImu = selectedProjectId === 0;
  const { data: projectResources } = useProjectResources(selectedProjectId);
  const { data: projectConversations } = useProjectConversations(selectedProjectId);
  const { data: imuConversations } = useImuConversations();
  const conversationItems = useMemo(
    () => {
      if (selectedProjectId === 0) {
        return (imuConversations ?? []).map((c) => ({ id: c.id, title: c.title }));
      }
      return (projectConversations?.items ?? []).map((c) => ({ id: c.id, title: c.title }));
    },
    [selectedProjectId, projectConversations, imuConversations],
  );
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
    if (open) {
      resetForm();
    }
  }, [open]);

  function resetForm() {
    setName("");
    setProjectId("");
    setTask("");
    setRunAt("");
    setRole("");
    setSystemPrompt("");
    setConversationId("none");
    setAdvancedOpen(false);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    try {
      const pid = Number(projectId);
      let resolvedConvId: number | null = null;
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

      // Convert local datetime-local value to ISO with timezone
      const dt = new Date(runAt);
      await createSchedule.mutateAsync({
        name: name.trim(),
        project_id: pid,
        task: task.trim(),
        run_at: dt.toISOString(),
        role: role.trim() || undefined,
        system_prompt: systemPrompt.trim() || undefined,
        conversation_id: resolvedConvId,
      });
      resetForm();
      onOpenChange(false);
    } catch {
      // error displayed via mutation state
    }
  }

  // Minimum datetime for the input (now + 1 minute)
  const minDateTime = useMemo(() => {
    const d = new Date(Date.now() + 60_000);
    d.setSeconds(0, 0);
    return d.toISOString().slice(0, 16);
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Create One-Time Schedule</DialogTitle>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="ot-name">
              Name <span className="text-destructive">*</span>
            </Label>
            <Input
              id="ot-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. deploy-tonight"
              required
              autoFocus
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="ot-project">
              Project <span className="text-destructive">*</span>
            </Label>
            <Select value={projectId} onValueChange={setProjectId} required>
              <SelectTrigger id="ot-project">
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

          <div className="space-y-2">
            <Label htmlFor="ot-task">
              Task <span className="text-destructive">*</span>
            </Label>
            <Textarea
              id="ot-task"
              value={task}
              onChange={(e) => setTask(e.target.value)}
              placeholder="What should the agent do?"
              required
              rows={3}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="ot-run-at">
              Run At <span className="text-destructive">*</span>
            </Label>
            <Input
              id="ot-run-at"
              type="datetime-local"
              value={runAt}
              onChange={(e) => setRunAt(e.target.value)}
              min={minDateTime}
              required
            />
            <p className="text-xs text-muted-foreground">
              Schedule will fire once at this time and then auto-disable.
            </p>
          </div>

          <div className="space-y-2">
            <Label htmlFor="ot-role">Role</Label>
            <Input
              id="ot-role"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              placeholder={roles[0] ?? "orchestrator"}
              list="ot-role-list"
              disabled={isImu}
            />
            <datalist id="ot-role-list">
              {roles.map((r) => (
                <option key={r} value={r} />
              ))}
            </datalist>
            {!isImu && role.trim() && roles.length > 0 && !roles.includes(role.trim()) && (
              <p className="text-xs text-destructive">Role not found in installed roles</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="ot-conversation">Conversation</Label>
            <Select value={conversationId} onValueChange={setConversationId}>
              <SelectTrigger id="ot-conversation">
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
                ? "Starts a standalone session."
                : conversationId === "new"
                  ? "A new conversation will be created for this run."
                  : "Continues this conversation's context."}
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
                <Label htmlFor="ot-prompt">System Prompt</Label>
                <Textarea
                  id="ot-prompt"
                  value={systemPrompt}
                  onChange={(e) => setSystemPrompt(e.target.value)}
                  placeholder="Additional instructions for the agent..."
                  rows={3}
                />
              </div>
            </CollapsibleContent>
          </Collapsible>

          {createSchedule.error && (
            <p className="text-sm text-destructive">
              {(createSchedule.error as Error).message}
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
            <Button
              type="submit"
              disabled={createSchedule.isPending || createConversation.isPending || createImuConversation.isPending || (!!role.trim() && roles.length > 0 && !roles.includes(role.trim()))}
            >
              {createSchedule.isPending ? "Creating..." : "Create"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
