import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useProject, useProjectConfig } from "@/hooks/queries/use-projects";
import { useProjectSessions } from "@/hooks/queries/use-sessions";
import { useRoles } from "@/hooks/queries/use-roles";
import { useLaunchSession } from "@/hooks/mutations/use-sessions";
import SessionTable from "@/components/SessionTable";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { AlertCircle, ArrowLeft, ChevronDown, Play } from "lucide-react";

export default function ProjectDetail() {
  const { projectId } = useParams();
  const pid = Number(projectId);
  const project = useProject(pid);
  const sessions = useProjectSessions(pid);
  const [showLaunch, setShowLaunch] = useState(false);

  const loading = project.isLoading || sessions.isLoading;
  const error = project.error || sessions.error;

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-24 rounded-lg" />
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
  if (!project.data) {
    return (
      <div className="flex items-center gap-2 text-destructive">
        <AlertCircle className="h-4 w-4" />
        <span>Project not found</span>
      </div>
    );
  }

  const p = project.data;
  const sessionList = sessions.data ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">{p.display_name}</h1>
        <div className="flex gap-2">
          <Button onClick={() => setShowLaunch(true)} disabled={!p.dir_exists}>
            <Play className="mr-2 h-4 w-4" />
            Launch Session
          </Button>
          <Button variant="outline" asChild>
            <Link to="/projects">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back
            </Link>
          </Button>
        </div>
      </div>

      <Card>
        <CardContent className="pt-6">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="font-medium text-muted-foreground">Directory</dt>
            <dd className="flex items-center gap-2 break-all">
              {p.working_dir}
              {p.dir_exists ? (
                <Badge
                  variant="outline"
                  className="border-green-200 bg-green-50 text-xs text-green-700"
                >
                  OK
                </Badge>
              ) : (
                <Badge
                  variant="outline"
                  className="border-orange-200 bg-orange-50 text-xs text-orange-700"
                >
                  Missing
                </Badge>
              )}
            </dd>
            <dt className="font-medium text-muted-foreground">Created</dt>
            <dd>{new Date(p.created_at).toLocaleString()}</dd>
          </dl>
        </CardContent>
      </Card>

      {showLaunch && (
        <LaunchForm
          projectId={pid}
          onLaunched={() => setShowLaunch(false)}
          onCancel={() => setShowLaunch(false)}
        />
      )}

      <section className="space-y-3">
        <h2 className="text-sm font-medium text-muted-foreground">
          Sessions ({sessionList.length})
        </h2>
        {sessionList.length === 0 ? (
          <p className="text-sm italic text-muted-foreground">
            No sessions yet.
          </p>
        ) : (
          <Card>
            <CardContent className="p-0">
              <SessionTable sessions={sessionList} />
            </CardContent>
          </Card>
        )}
      </section>
    </div>
  );
}

function LaunchForm({
  projectId,
  onLaunched,
  onCancel,
}: {
  projectId: number;
  onLaunched: () => void;
  onCancel: () => void;
}) {
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
      onLaunched();
      navigate(`/projects/${projectId}/sessions/${result.run_id}`);
    } catch {
      // error state handled by mutation
    }
  };

  const defaultRole = defaults?.orchestrator_role ?? "orchestrator";
  const installedRoles = (roles.data ?? []).filter((v) => v !== defaultRole);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Launch Session</CardTitle>
      </CardHeader>
      <CardContent>
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
            <Button type="button" variant="outline" onClick={onCancel}>
              Cancel
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
