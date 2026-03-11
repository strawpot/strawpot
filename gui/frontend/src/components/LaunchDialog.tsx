import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useProjectConfig, useProjectFiles } from "@/hooks/queries/use-projects";
import { useRoles } from "@/hooks/queries/use-roles";
import { useResources } from "@/hooks/queries/use-registry";
import { useResourceConfig } from "@/hooks/queries/use-resource-config";
import { useLaunchSession } from "@/hooks/mutations/use-sessions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
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
import { ChevronDown, Paperclip, X } from "lucide-react";

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
  const { data: agents } = useResources("agents");
  const { data: memories } = useResources("memories");
  const projectFiles = useProjectFiles(projectId);
  const launchSession = useLaunchSession();
  const defaults = config.data?.merged as
    | {
        orchestrator_role?: string;
        runtime?: string;
        memory?: string;
        cache_delegations?: boolean;
        cache_max_entries?: number;
        cache_ttl_seconds?: number;
        max_num_delegations?: number;
      }
    | undefined;

  // placeholder value for "Default" option in selects
  const EMPTY = "__empty__";

  const [task, setTask] = useState("");
  const [role, setRole] = useState("");
  const [runtime, setRuntime] = useState("");
  const [memory, setMemory] = useState("");
  const [cacheDelegations, setCacheDelegations] = useState("");
  const [cacheMaxEntries, setCacheMaxEntries] = useState("");
  const [cacheTtlSeconds, setCacheTtlSeconds] = useState("");
  const [maxNumDelegations, setMaxNumDelegations] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [interactive, setInteractive] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [fileFilter, setFileFilter] = useState("");

  const resetForm = () => {
    setTask("");
    setRole("");
    setRuntime("");
    setMemory("");
    setCacheDelegations("");
    setCacheMaxEntries("");
    setCacheTtlSeconds("");
    setMaxNumDelegations("");
    setSystemPrompt("");
    setInteractive(false);
    setSelectedFiles([]);
  };

  const toggleFile = (path: string) => {
    setSelectedFiles((prev) =>
      prev.includes(path) ? prev.filter((p) => p !== path) : [...prev, path],
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const body: {
        project_id: number;
        task: string;
        role?: string;
        overrides?: Record<string, unknown>;
        context_files?: string[];
        system_prompt?: string;
        interactive?: boolean;
      } = {
        project_id: projectId,
        task: task.trim(),
      };
      if (role.trim()) body.role = role.trim();

      const overrides: Record<string, unknown> = {};
      if (runtime.trim()) overrides.runtime = runtime.trim();
      if (memory.trim()) overrides.memory = memory.trim();
      if (cacheDelegations) overrides.cache_delegations = cacheDelegations === "true";
      if (cacheMaxEntries.trim()) overrides.cache_max_entries = Number(cacheMaxEntries.trim());
      if (cacheTtlSeconds.trim()) overrides.cache_ttl_seconds = Number(cacheTtlSeconds.trim());
      if (maxNumDelegations.trim()) overrides.max_num_delegations = Number(maxNumDelegations.trim());
      if (Object.keys(overrides).length > 0) body.overrides = overrides;
      if (selectedFiles.length > 0) body.context_files = selectedFiles;
      if (systemPrompt.trim()) body.system_prompt = systemPrompt.trim();
      if (interactive) body.interactive = true;

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
  const allRoles = [defaultRole, ...installedRoles];
  const agentNames = (agents ?? []).map((a) => a.name);
  const memoryNames = new Set((memories ?? []).map((m) => m.name));
  memoryNames.add("none");
  const memoryOptions = [...memoryNames].sort();

  // Resolve runtime placeholder: role's default_agent (if available) > project runtime
  const effectiveRole = role.trim() || defaultRole;
  const roleConfig = useResourceConfig("roles", effectiveRole, {
    enabled: !!effectiveRole,
  });
  const roleDefaultAgent =
    (roleConfig.data?.params_values?.default_agent as string) ??
    (roleConfig.data?.params_schema?.default_agent?.default as string) ??
    "";
  const runtimePlaceholder =
    roleDefaultAgent && agentNames.includes(roleDefaultAgent)
      ? roleDefaultAgent
      : defaults?.runtime ?? "strawpot-claude-code";

  const roleError =
    role.trim() && !allRoles.includes(role.trim())
      ? "Role not found in installed roles"
      : "";
  const runtimeError =
    runtime.trim() && agentNames.length > 0 && !agentNames.includes(runtime.trim())
      ? "Runtime not found in installed agents"
      : "";
  const memoryError =
    memory.trim() && !memoryOptions.includes(memory.trim())
      ? "Memory not found in installed providers"
      : "";
  const hasValidationError = !!roleError || !!runtimeError || !!memoryError;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
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
          {(projectFiles.data ?? []).length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button type="button" variant="outline" size="sm">
                      <Paperclip className="mr-1 h-3.5 w-3.5" />
                      @ Attach Files
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start" className="w-64" onCloseAutoFocus={(e) => e.preventDefault()}>
                    <div className="px-2 py-1.5">
                      <Input
                        placeholder="Filter files..."
                        value={fileFilter}
                        onChange={(e) => setFileFilter(e.target.value)}
                        className="h-7 text-xs"
                        onKeyDown={(e) => e.stopPropagation()}
                      />
                    </div>
                    <div className="max-h-48 overflow-y-auto">
                      {(projectFiles.data ?? [])
                        .filter((f) =>
                          f.path.toLowerCase().includes(fileFilter.toLowerCase()),
                        )
                        .map((f) => (
                          <DropdownMenuCheckboxItem
                            key={f.path}
                            checked={selectedFiles.includes(f.path)}
                            onCheckedChange={() => toggleFile(f.path)}
                            onSelect={(e) => e.preventDefault()}
                          >
                            <span className="font-mono text-xs">{f.path}</span>
                          </DropdownMenuCheckboxItem>
                        ))}
                    </div>
                  </DropdownMenuContent>
                </DropdownMenu>
                {selectedFiles.length > 0 && (
                  <span className="text-xs text-muted-foreground">
                    {selectedFiles.length} file(s) attached
                  </span>
                )}
              </div>
              {selectedFiles.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {selectedFiles.map((path) => (
                    <Badge
                      key={path}
                      variant="secondary"
                      className="gap-1 font-mono text-xs"
                    >
                      @{path}
                      <button
                        type="button"
                        onClick={() => toggleFile(path)}
                        className="ml-0.5 rounded-sm hover:bg-muted"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="space-y-2">
            <Label htmlFor="role">Role</Label>
            <Input
              id="role"
              list="datalist-role"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              placeholder={defaultRole}
            />
            <datalist id="datalist-role">
              <option value={defaultRole} />
              {installedRoles.map((v) => (
                <option key={v} value={v} />
              ))}
            </datalist>
            {roleError && (
              <p className="text-xs text-destructive">{roleError}</p>
            )}
          </div>

          <Collapsible>
            <CollapsibleTrigger asChild>
              <Button type="button" variant="ghost" size="sm">
                <ChevronDown className="mr-1 h-4 w-4" />
                Advanced Options
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-3 space-y-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={interactive}
                  onChange={(e) => setInteractive(e.target.checked)}
                  className="rounded border-input"
                />
                <span className="text-sm">
                  Interactive mode
                </span>
                <span className="text-xs text-muted-foreground">
                  Allow the agent to ask you questions via a chat panel
                </span>
              </label>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="runtime">Runtime</Label>
                  <Input
                    id="runtime"
                    list="datalist-runtime"
                    value={runtime}
                    onChange={(e) => setRuntime(e.target.value)}
                    placeholder={runtimePlaceholder}
                  />
                  {agents && (
                    <datalist id="datalist-runtime">
                      {agents.map((a) => (
                        <option key={a.name} value={a.name} />
                      ))}
                    </datalist>
                  )}
                  {runtimeError && (
                    <p className="text-xs text-destructive">{runtimeError}</p>
                  )}
                </div>
                <div className="space-y-2">
                  <Label htmlFor="memory">Memory</Label>
                  <Input
                    id="memory"
                    list="datalist-memory"
                    value={memory}
                    onChange={(e) => setMemory(e.target.value)}
                    placeholder={defaults?.memory || "dial"}
                  />
                  <datalist id="datalist-memory">
                    {memoryOptions.map((n) => (
                      <option key={n} value={n} />
                    ))}
                  </datalist>
                  {memoryError && (
                    <p className="text-xs text-destructive">{memoryError}</p>
                  )}
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="system-prompt">System Prompt</Label>
                <Textarea
                  id="system-prompt"
                  value={systemPrompt}
                  onChange={(e) => setSystemPrompt(e.target.value)}
                  placeholder="Additional instructions for the agent..."
                  rows={3}
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Max Delegations</Label>
                  <Input
                    type="number"
                    min="0"
                    value={maxNumDelegations}
                    onChange={(e) => setMaxNumDelegations(e.target.value)}
                    placeholder={defaults?.max_num_delegations ? String(defaults.max_num_delegations) : "0 (unlimited)"}
                    className="h-8 text-xs"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Cache Delegations</Label>
                  <Select
                    value={cacheDelegations || EMPTY}
                    onValueChange={(v) => setCacheDelegations(v === EMPTY ? "" : v)}
                  >
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue
                        placeholder={defaults?.cache_delegations !== false ? "true" : "false"}
                      />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={EMPTY} className="text-muted-foreground">
                        Default ({defaults?.cache_delegations !== false ? "true" : "false"})
                      </SelectItem>
                      <SelectItem value="true">true</SelectItem>
                      <SelectItem value="false">false</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Cache Max Entries</Label>
                  <Input
                    type="number"
                    min="0"
                    value={cacheMaxEntries}
                    onChange={(e) => setCacheMaxEntries(e.target.value)}
                    placeholder={defaults?.cache_max_entries ? String(defaults.cache_max_entries) : "0 (unlimited)"}
                    className="h-8 text-xs"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Cache TTL (seconds)</Label>
                  <Input
                    type="number"
                    min="0"
                    value={cacheTtlSeconds}
                    onChange={(e) => setCacheTtlSeconds(e.target.value)}
                    placeholder={defaults?.cache_ttl_seconds ? String(defaults.cache_ttl_seconds) : "0 (unlimited)"}
                    className="h-8 text-xs"
                  />
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
            <Button type="submit" disabled={launchSession.isPending || hasValidationError}>
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
