import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useProjectConfig } from "@/hooks/queries/use-projects";
import { useRoles } from "@/hooks/queries/use-roles";
import { useLaunchSession } from "@/hooks/mutations/use-sessions";
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

interface LaunchDialogProps {
  projectId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export default function LaunchDialog({
  projectId,
  open,
  onOpenChange,
}: LaunchDialogProps) {
  const navigate = useNavigate();
  const config = useProjectConfig(projectId);
  const roles = useRoles();
  const launchSession = useLaunchSession();
  const defaults = config.data?.merged;

  const [task, setTask] = useState("");
  const [role, setRole] = useState("");
  const [runtime, setRuntime] = useState("");
  const [isolation, setIsolation] = useState("");
  const [mergeStrategy, setMergeStrategy] = useState("");

  const resetForm = () => {
    setTask("");
    setRole("");
    setRuntime("");
    setIsolation("");
    setMergeStrategy("");
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const body: {
        project_id: number;
        task: string;
        role?: string;
        overrides?: Record<string, string>;
      } = {
        project_id: projectId,
        task: task.trim(),
      };
      if (role.trim()) body.role = role.trim();

      const overrides: Record<string, string> = {};
      if (runtime.trim()) overrides.runtime = runtime.trim();
      if (isolation.trim()) overrides.isolation = isolation.trim();
      if (mergeStrategy.trim()) overrides.merge_strategy = mergeStrategy.trim();
      if (Object.keys(overrides).length > 0) body.overrides = overrides;

      const result = await launchSession.mutateAsync(body);
      resetForm();
      onOpenChange(false);
      navigate(`/projects/${projectId}/sessions/${result.run_id}`);
    } catch {
      // error state handled by mutation
    }
  };

  const defaultRole = defaults?.orchestrator_role ?? "orchestrator";
  const installedRoles = (roles.data ?? []).filter((v) => v !== defaultRole);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Launch Session</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="task">
              Task <span className="text-destructive">*</span>
            </Label>
            <Textarea
              id="task"
              value={task}
              onChange={(e) => setTask(e.target.value)}
              placeholder="Describe what the agent should do..."
              required
              autoFocus
              rows={3}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="role">Role</Label>
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger id="role">
                <SelectValue placeholder={defaultRole} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={defaultRole}>{defaultRole}</SelectItem>
                {installedRoles.map((v) => (
                  <SelectItem key={v} value={v}>
                    {v}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <Collapsible>
            <CollapsibleTrigger asChild>
              <Button type="button" variant="ghost" size="sm">
                <ChevronDown className="mr-1 h-4 w-4" />
                Advanced Options
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-3 space-y-4">
              <div className="grid grid-cols-3 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="runtime">Runtime</Label>
                  <Input
                    id="runtime"
                    value={runtime}
                    onChange={(e) => setRuntime(e.target.value)}
                    placeholder={defaults?.runtime ?? "strawpot-claude-code"}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="isolation">Isolation</Label>
                  <Select value={isolation} onValueChange={setIsolation}>
                    <SelectTrigger id="isolation">
                      <SelectValue
                        placeholder={defaults?.isolation ?? "none"}
                      />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">none</SelectItem>
                      <SelectItem value="worktree">worktree</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="merge-strategy">Merge Strategy</Label>
                  <Select
                    value={mergeStrategy}
                    onValueChange={setMergeStrategy}
                  >
                    <SelectTrigger id="merge-strategy">
                      <SelectValue
                        placeholder={defaults?.merge_strategy ?? "auto"}
                      />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="auto">auto</SelectItem>
                      <SelectItem value="local">local</SelectItem>
                      <SelectItem value="pr">pr</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </CollapsibleContent>
          </Collapsible>

          {launchSession.error && (
            <p className="text-sm text-destructive">
              {launchSession.error.message}
            </p>
          )}
          <div className="flex gap-2">
            <Button type="submit" disabled={launchSession.isPending}>
              {launchSession.isPending ? "Launching..." : "Launch"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
