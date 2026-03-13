import { useState } from "react";
import type { ResourceDetail } from "@/api/types";
import {
  useUninstallResource,
  useUpdateResource,
  useReinstallResource,
} from "@/hooks/mutations/use-registry";
import {
  useUninstallProjectResource,
  useUpdateProjectResource,
  useReinstallProjectResource,
} from "@/hooks/mutations/use-project-resources";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { ScrollArea } from "@/components/ui/scroll-area";
import AgentSetupGuide from "@/components/AgentSetupGuide";
import ResourceConfigForm from "@/components/ResourceConfigForm";
import { toast } from "sonner";

interface Props {
  resource: ResourceDetail | null;
  resourceType: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId?: number;
}

export default function ResourceDetailSheet({
  resource,
  resourceType,
  open,
  onOpenChange,
  projectId,
}: Props) {
  // Global mutations
  const globalUninstall = useUninstallResource();
  const globalUpdate = useUpdateResource();
  const globalReinstall = useReinstallResource();

  // Project mutations (always instantiated; idle when not used)
  const projUninstall = useUninstallProjectResource(projectId ?? 0);
  const projUpdate = useUpdateProjectResource(projectId ?? 0);
  const projReinstall = useReinstallProjectResource(projectId ?? 0);

  // Pick the right set based on scope
  const uninstall = projectId ? projUninstall : globalUninstall;
  const updateResource = projectId ? projUpdate : globalUpdate;
  const reinstall = projectId ? projReinstall : globalReinstall;

  const [confirming, setConfirming] = useState(false);
  const actionPending = updateResource.isPending || reinstall.isPending || uninstall.isPending;

  if (!resource) return null;

  const handleUninstall = () => {
    if (!confirming) {
      setConfirming(true);
      return;
    }
    uninstall.mutate(
      { type: resourceType, name: resource.name },
      {
        onSuccess: (result) => {
          if (result.exit_code === 0) {
            toast.success(`Uninstalled ${resource.name}`);
            onOpenChange(false);
          } else {
            toast.error(`Uninstall failed: ${result.stderr || result.stdout}`);
          }
          setConfirming(false);
        },
        onError: () => {
          toast.error("Uninstall request failed");
          setConfirming(false);
        },
      },
    );
  };

  const handleUpdate = () => {
    updateResource.mutate(
      { type: resourceType, name: resource.name },
      {
        onSuccess: (result) => {
          if (result.exit_code === 0) {
            toast.success(`Updated ${resource.name}`);
          } else {
            toast.error(`Update failed: ${result.stderr || result.stdout}`);
          }
        },
        onError: () => toast.error("Update request failed"),
      },
    );
  };

  const handleReinstall = () => {
    reinstall.mutate(
      { type: resourceType, name: resource.name },
      {
        onSuccess: (result) => {
          if (result.exit_code === 0) {
            toast.success(`Reinstalled ${resource.name}`);
          } else {
            toast.error(`Reinstall failed: ${result.stderr || result.stdout}`);
          }
        },
        onError: () => toast.error("Reinstall request failed"),
      },
    );
  };

  // Built-in resources that cannot be uninstalled.
  // IMPORTANT: Keep in sync with registry.py (_PROTECTED_ROLES/SKILLS/AGENTS/MEMORIES)
  // and ResourceBrowser.tsx — all three must be updated together.
  const PROTECTED: Record<string, string[]> = {
    skills: ["denden", "strawpot-session-recap"],
    roles: ["imu", "ai-ceo", "ai-employee"],
    agents: ["strawpot-claude-code"],
    memories: ["dial"],
  };
  const isProtected = PROTECTED[resourceType]?.includes(resource.name) ?? false;

  const metadata = resource.frontmatter?.metadata as Record<string, unknown> | undefined;

  return (
    <Sheet open={open} onOpenChange={(v) => { onOpenChange(v); setConfirming(false); }}>
      <SheetContent side="right" className="flex h-full flex-col sm:max-w-xl overflow-x-hidden">
        <SheetHeader className="shrink-0">
          <SheetTitle className="flex items-center gap-2">
            {resource.name}
            {resource.version && (
              <Badge variant="outline" className="text-xs font-normal">
                v{resource.version}
              </Badge>
            )}
          </SheetTitle>
          <SheetDescription>{resource.description || "No description"}</SheetDescription>
        </SheetHeader>

        <div className="shrink-0 flex flex-col gap-4 px-4">
          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
            <span>Source: <strong>{resource.source}</strong></span>
            <span>Path: <code className="rounded bg-muted px-1">{resource.path}</code></span>
          </div>

          {metadata && Object.keys(metadata).length > 0 && (
            <details className="text-sm">
              <summary className="cursor-pointer font-medium text-muted-foreground">
                Metadata
              </summary>
              <pre className="mt-2 max-h-40 overflow-auto rounded-md bg-muted p-3 text-xs">
                {JSON.stringify(metadata, null, 2)}
              </pre>
            </details>
          )}
        </div>

        <ScrollArea className="min-h-0 flex-1">
          <div className="px-4 overflow-hidden">
            {resourceType === "agents" && (
              <AgentSetupGuide agentName={resource.name} />
            )}
            <ResourceConfigForm
              resourceType={resourceType}
              resourceName={resource.name}
              enabled={open}
              projectId={projectId}
            />
            <div className="prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap mt-4">
              {resource.body || "No content."}
            </div>
          </div>
        </ScrollArea>

        <div className="shrink-0 border-t border-border p-4 flex gap-2">
          <Button
            size="sm"
            onClick={handleUpdate}
            disabled={actionPending}
          >
            {updateResource.isPending ? "Updating..." : "Update"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleReinstall}
            disabled={actionPending}
          >
            {reinstall.isPending ? "Reinstalling..." : "Reinstall"}
          </Button>
          <div className="flex-1" />
          {!isProtected && (
            <>
              <Button
                variant={confirming ? "destructive" : "outline"}
                size="sm"
                onClick={handleUninstall}
                disabled={actionPending}
              >
                {uninstall.isPending
                  ? "Uninstalling..."
                  : confirming
                    ? "Confirm Uninstall"
                    : "Uninstall"}
              </Button>
              {confirming && !uninstall.isPending && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setConfirming(false)}
                >
                  Cancel
                </Button>
              )}
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
