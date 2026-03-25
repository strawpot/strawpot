import { useState } from "react";
import { useProjectResources, useProjectResourceDetail } from "@/hooks/queries/use-project-resources";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import ResourceDetailSheet from "@/components/ResourceDetailSheet";
import InstallDialog from "@/components/InstallDialog";
import UpdateAllDialog from "@/components/UpdateAllDialog";
import ProjectIntegrationsTab from "@/components/ProjectIntegrationsTab";
import {
  useUninstallProjectResource,
  useUpdateAllProjectResources,
} from "@/hooks/mutations/use-project-resources";
import { useIntegrations } from "@/hooks/queries/use-integrations";
import { Download, RefreshCw, Settings, Trash2 } from "lucide-react";
import { toast } from "sonner";
import type { ProjectResource } from "@/api/types";

const RESOURCE_TYPES = ["roles", "skills", "agents", "memories"] as const;

const TYPE_LABELS: Record<string, string> = {
  roles: "Roles",
  skills: "Skills",
  agents: "Agents",
  memories: "Memories",
  integrations: "Integrations",
};

interface Props {
  projectId: number;
  installOpen?: boolean;
  onInstallOpenChange?: (open: boolean) => void;
}

export default function ProjectResourcesTab({
  projectId,
  installOpen: externalInstallOpen,
  onInstallOpenChange: externalOnInstallOpenChange,
}: Props) {
  const { data: resources, isLoading } = useProjectResources(projectId);
  const { data: integrations } = useIntegrations(projectId);
  const integrationCount = (integrations ?? []).length;
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [selectedType, setSelectedType] = useState<string>("");
  const [sheetOpen, setSheetOpen] = useState(false);
  const [internalInstallOpen, setInternalInstallOpen] = useState(false);

  const [updateAllOpen, setUpdateAllOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<string>("all");
  const updateAll = useUpdateAllProjectResources(projectId);

  const installOpen = externalInstallOpen ?? internalInstallOpen;
  const setInstallOpen = externalOnInstallOpenChange ?? setInternalInstallOpen;

  // Determine the resource type for scoped updates (undefined = all types)
  const UPDATABLE_TYPES: readonly string[] = [...RESOURCE_TYPES, "integrations"];
  const activeResourceType = UPDATABLE_TYPES.includes(activeTab)
    ? activeTab
    : undefined;
  const updateLabel = activeResourceType ? (TYPE_LABELS[activeResourceType] ?? activeResourceType) : null;

  const { data: detail } = useProjectResourceDetail(
    projectId,
    selectedType,
    selectedName ?? "",
    { enabled: sheetOpen && !!selectedName && !!selectedType },
  );

  const openDetail = (r: ProjectResource) => {
    setSelectedName(r.name);
    setSelectedType(r.type);
    setSheetOpen(true);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Resources available to this project
        </p>
        <div className="flex gap-2">
          <Button onClick={() => setUpdateAllOpen(true)} size="sm" variant="outline">
            <RefreshCw className="mr-2 h-4 w-4" />
            Update All{updateLabel ? ` ${updateLabel}` : ""}
          </Button>
          <Button onClick={() => setInstallOpen(true)} size="sm">
            <Download className="mr-2 h-4 w-4" />
            Install
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : !resources || (resources.length === 0 && integrationCount === 0) ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center text-muted-foreground">
          No resources available yet.
        </div>
      ) : (
        <Tabs defaultValue={resources.length > 0 ? "all" : "integrations"} onValueChange={setActiveTab}>
          <TabsList>
            <TabsTrigger value="all">All</TabsTrigger>
            {RESOURCE_TYPES.map((t) => {
              const count = resources.filter((r) => r.type === t).length;
              return (
                <TabsTrigger key={t} value={t} disabled={count === 0}>
                  {TYPE_LABELS[t]} ({count})
                </TabsTrigger>
              );
            })}
            <TabsTrigger value="integrations">
              Integrations ({integrationCount})
            </TabsTrigger>
          </TabsList>

          <TabsContent value="all">
            <ResourceTable
              resources={resources}
              showType
              projectId={projectId}
              onSelect={openDetail}
            />
          </TabsContent>
          {RESOURCE_TYPES.map((t) => (
            <TabsContent key={t} value={t}>
              <ResourceTable
                resources={resources.filter((r) => r.type === t)}
                projectId={projectId}
                onSelect={openDetail}
              />
            </TabsContent>
          ))}
          <TabsContent value="integrations">
            <ProjectIntegrationsTab projectId={projectId} />
          </TabsContent>
        </Tabs>
      )}

      <ResourceDetailSheet
        resource={detail ?? null}
        resourceType={selectedType}
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        projectId={projectId}
      />

      <InstallDialog
        open={installOpen}
        onOpenChange={setInstallOpen}
        projectId={projectId}
      />

      <UpdateAllDialog
        open={updateAllOpen}
        onOpenChange={setUpdateAllOpen}
        onUpdate={() => updateAll.mutateAsync(activeResourceType)}
        scope="project"
        resourceType={activeResourceType}
      />
    </div>
  );
}

function ResourceTable({
  resources,
  showType,
  projectId,
  onSelect,
}: {
  resources: ProjectResource[];
  showType?: boolean;
  projectId: number;
  onSelect: (r: ProjectResource) => void;
}) {
  if (resources.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border p-8 text-center text-muted-foreground">
        No resources in this category.
      </div>
    );
  }

  return (
    <Card>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Source</TableHead>
              {showType && <TableHead>Type</TableHead>}
              <TableHead>Version</TableHead>
              <TableHead>Description</TableHead>
              <TableHead>Config</TableHead>
              <TableHead className="w-24" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {resources.map((r) => (
              <TableRow
                key={`${r.type}-${r.name}`}
                className="cursor-pointer"
                onClick={() => onSelect(r)}
              >
                <TableCell className="font-medium">{r.name}</TableCell>
                <TableCell>
                  <Badge
                    variant="outline"
                    className={`text-xs ${r.source === "global" ? "border-dashed" : ""}`}
                  >
                    {r.source === "global" ? "Global" : "Project"}
                  </Badge>
                </TableCell>
                {showType && (
                  <TableCell>
                    <Badge variant="outline" className="text-xs">
                      {TYPE_LABELS[r.type] ?? r.type}
                    </Badge>
                  </TableCell>
                )}
                <TableCell className="text-sm text-muted-foreground">
                  {r.version ?? "—"}
                </TableCell>
                <TableCell className="max-w-[300px] truncate text-sm">
                  {r.description || "—"}
                </TableCell>
                <TableCell>
                  {r.config_count > 0 && (
                    <Badge variant="secondary" className="text-xs gap-1">
                      <Settings className="h-3 w-3" />
                      {r.config_count}
                    </Badge>
                  )}
                </TableCell>
                <TableCell>
                  {r.source === "project" && (
                    <ProjectUninstallButton
                      projectId={projectId}
                      resourceType={r.type}
                      name={r.name}
                    />
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function ProjectUninstallButton({
  projectId,
  resourceType,
  name,
}: {
  projectId: number;
  resourceType: string;
  name: string;
}) {
  const [confirming, setConfirming] = useState(false);
  const uninstall = useUninstallProjectResource(projectId);

  const handleUninstall = (e: React.MouseEvent) => {
    e.stopPropagation();
    uninstall.mutate(
      { type: resourceType, name },
      {
        onSuccess: (result) => {
          if (result.exit_code === 0) {
            toast.success(`Uninstalled ${name}`);
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

  if (confirming) {
    return (
      <div className="flex gap-1">
        <Button
          size="sm"
          variant="destructive"
          onClick={handleUninstall}
          disabled={uninstall.isPending}
        >
          Confirm
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={(e) => {
            e.stopPropagation();
            setConfirming(false);
          }}
        >
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
      onClick={(e) => {
        e.stopPropagation();
        setConfirming(true);
      }}
    >
      <Trash2 className="h-4 w-4" />
    </Button>
  );
}
