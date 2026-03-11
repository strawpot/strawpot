import { useState } from "react";
import { Link } from "react-router-dom";
import { useProjects } from "@/hooks/queries/use-projects";
import { useGlobalConfig } from "@/hooks/queries/use-config";
import { useCreateProject, useDeleteProject } from "@/hooks/mutations/use-projects";
import { useSaveProjectConfig } from "@/hooks/mutations/use-config";
import { api } from "@/api/client";
import DirBrowser from "@/components/DirBrowser";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { AlertCircle, Plus, Trash2 } from "lucide-react";

export default function ProjectList() {
  const { data: projects, isLoading, error } = useProjects();
  const [showForm, setShowForm] = useState(false);

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-32" />
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

  const list = projects ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Projects</h1>
        <Button onClick={() => setShowForm(true)}>
          <Plus className="mr-2 h-4 w-4" />
          Add Project
        </Button>
      </div>

      {showForm && (
        <RegisterForm
          onDone={() => setShowForm(false)}
          onCancel={() => setShowForm(false)}
        />
      )}

      {list.length === 0 ? (
        <p className="text-sm italic text-muted-foreground">
          No projects registered yet.
        </p>
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Directory</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="w-[80px]" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell>
                      <Link
                        to={`/projects/${p.id}`}
                        className="text-sm font-medium text-primary underline-offset-4 hover:underline"
                      >
                        {p.display_name}
                      </Link>
                    </TableCell>
                    <TableCell className="max-w-[300px] truncate text-sm text-muted-foreground">
                      {p.working_dir}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatDate(p.created_at)}
                    </TableCell>
                    <TableCell>
                      {p.dir_exists ? (
                        <Badge
                          variant="outline"
                          className="border-green-200 bg-green-50 text-xs text-green-700 dark:border-green-800 dark:bg-green-950 dark:text-green-400"
                        >
                          OK
                        </Badge>
                      ) : (
                        <Badge
                          variant="outline"
                          className="border-orange-200 bg-orange-50 text-xs text-orange-700 dark:border-orange-800 dark:bg-orange-950 dark:text-orange-400"
                        >
                          Missing
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      <DeleteButton projectId={p.id} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function RegisterForm({
  onDone,
  onCancel,
}: {
  onDone: () => void;
  onCancel: () => void;
}) {
  const [displayName, setDisplayName] = useState("");
  const [workingDir, setWorkingDir] = useState("");
  const [isolation, setIsolation] = useState("");
  const [mergeStrategy, setMergeStrategy] = useState("");
  const [showBrowser, setShowBrowser] = useState(false);
  const [gitInitPrompt, setGitInitPrompt] = useState(false);
  const createProject = useCreateProject();
  const saveConfig = useSaveProjectConfig();
  const globalConfig = useGlobalConfig();

  const globalDefaults = globalConfig.data?.defaults as
    | { isolation?: string; session?: { merge_strategy?: string } }
    | undefined;
  const defaultIsolation = globalDefaults?.isolation ?? "none";
  const defaultMergeStrategy = globalDefaults?.session?.merge_strategy ?? "auto";

  const effectiveIsolation = isolation || defaultIsolation;

  const doCreate = async () => {
    const project = await createProject.mutateAsync({
      display_name: displayName.trim(),
      working_dir: workingDir.trim(),
    });
    const configData: Record<string, unknown> = {};
    const selectedMergeStrategy = mergeStrategy || defaultMergeStrategy;
    configData.isolation = effectiveIsolation;
    configData.session = { merge_strategy: selectedMergeStrategy };
    await saveConfig.mutateAsync({
      projectId: (project as { id: number }).id,
      data: configData,
    });
    onDone();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      if (effectiveIsolation === "worktree" && workingDir.trim()) {
        const res = await api.get<{ is_git: boolean }>(
          `/fs/git-check?path=${encodeURIComponent(workingDir.trim())}`,
        );
        if (!res.is_git) {
          setGitInitPrompt(true);
          return;
        }
      }
      await doCreate();
    } catch {
      // error state handled by mutation
    }
  };

  const handleGitInitConfirm = async () => {
    try {
      await api.post("/fs/git-init", { path: workingDir.trim() });
      setGitInitPrompt(false);
      await doCreate();
    } catch {
      // error state handled by mutation
    }
  };

  return (
    <Card>
      <CardContent className="pt-6">
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="display-name">Display Name</Label>
              <Input
                id="display-name"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                required
                autoFocus
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="working-dir">Working Directory</Label>
              <div className="flex gap-2">
                <Input
                  id="working-dir"
                  value={workingDir}
                  onChange={(e) => setWorkingDir(e.target.value)}
                  placeholder="/path/to/project"
                  required
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setShowBrowser(!showBrowser)}
                >
                  Browse
                </Button>
              </div>
            </div>
          </div>
          {showBrowser && (
            <DirBrowser
              initialPath={workingDir || undefined}
              onSelect={(path) => {
                setWorkingDir(path);
                setShowBrowser(false);
              }}
              onCancel={() => setShowBrowser(false)}
            />
          )}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="isolation">Isolation</Label>
              <Select
                value={isolation || defaultIsolation}
                onValueChange={setIsolation}
              >
                <SelectTrigger id="isolation">
                  <SelectValue />
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
                value={mergeStrategy || defaultMergeStrategy}
                onValueChange={setMergeStrategy}
              >
                <SelectTrigger id="merge-strategy">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">auto</SelectItem>
                  <SelectItem value="local">local</SelectItem>
                  <SelectItem value="pr">pr</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          {gitInitPrompt && (
            <div className="rounded-md border border-orange-200 bg-orange-50 p-3 dark:border-orange-800 dark:bg-orange-950">
              <p className="text-sm">
                The selected directory is not a git repository. Worktree isolation requires git.
                Initialize a git repository with <code className="text-xs bg-muted px-1 py-0.5 rounded">git init</code>?
              </p>
              <div className="mt-2 flex gap-2">
                <Button type="button" size="sm" onClick={handleGitInitConfirm}>
                  Yes, initialize
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => setGitInitPrompt(false)}
                >
                  Cancel
                </Button>
              </div>
            </div>
          )}
          {(createProject.error || saveConfig.error) && (
            <p className="text-sm text-destructive">
              {(createProject.error || saveConfig.error)?.message}
            </p>
          )}
          <div className="flex gap-2">
            <Button type="submit" disabled={createProject.isPending || saveConfig.isPending}>
              {createProject.isPending || saveConfig.isPending ? "Adding..." : "Add"}
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

function DeleteButton({ projectId }: { projectId: number }) {
  const [confirming, setConfirming] = useState(false);
  const deleteProject = useDeleteProject();

  const handleDelete = async () => {
    try {
      await deleteProject.mutateAsync(projectId);
    } catch {
      // silently ignore — project may already be gone
    }
  };

  if (confirming) {
    return (
      <div className="flex gap-1">
        <Button
          size="sm"
          variant="destructive"
          onClick={handleDelete}
          disabled={deleteProject.isPending}
        >
          Confirm
        </Button>
        <Button size="sm" variant="outline" onClick={() => setConfirming(false)}>
          No
        </Button>
      </div>
    );
  }

  return (
    <Button
      size="sm"
      variant="ghost"
      className="text-muted-foreground hover:text-destructive"
      onClick={() => setConfirming(true)}
    >
      <Trash2 className="h-4 w-4" />
    </Button>
  );
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString();
  } catch {
    return iso;
  }
}
