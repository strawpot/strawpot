import { useEffect, useMemo, useState } from "react";
import { useProjects } from "@/hooks/queries/use-projects";
import { useProjectResources } from "@/hooks/queries/use-project-resources";
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

  const [name, setName] = useState("");
  const [projectId, setProjectId] = useState<string>("");
  const [task, setTask] = useState("");
  const [runAt, setRunAt] = useState("");
  const [role, setRole] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const selectedProjectId = Number(projectId) || 0;
  const { data: projectResources } = useProjectResources(selectedProjectId);
  const roles = useMemo(
    () =>
      (projectResources ?? [])
        .filter((r) => r.type === "roles")
        .map((r) => r.name),
    [projectResources],
  );

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
    setAdvancedOpen(false);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    try {
      // Convert local datetime-local value to ISO with timezone
      const dt = new Date(runAt);
      await createSchedule.mutateAsync({
        name: name.trim(),
        project_id: Number(projectId),
        task: task.trim(),
        run_at: dt.toISOString(),
        role: role.trim() || undefined,
        system_prompt: systemPrompt.trim() || undefined,
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
            />
            <datalist id="ot-role-list">
              {roles.map((r) => (
                <option key={r} value={r} />
              ))}
            </datalist>
            {role.trim() && roles.length > 0 && !roles.includes(role.trim()) && (
              <p className="text-xs text-destructive">Role not found in installed roles</p>
            )}
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
              disabled={createSchedule.isPending || (!!role.trim() && roles.length > 0 && !roles.includes(role.trim()))}
            >
              {createSchedule.isPending ? "Creating..." : "Create"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
