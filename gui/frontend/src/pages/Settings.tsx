import { useState } from "react";
import { useProjects, useProjectConfig } from "@/hooks/queries/use-projects";
import { useGlobalConfig } from "@/hooks/queries/use-config";
import { useSaveGlobalConfig, useSaveProjectConfig } from "@/hooks/mutations/use-config";
import ConfigForm from "@/components/ConfigForm";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

export default function Settings() {
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);

  const globalConfig = useGlobalConfig();
  const projects = useProjects();
  const projectConfig = useProjectConfig(selectedProjectId ?? 0, {
    enabled: selectedProjectId != null,
  });

  const saveGlobal = useSaveGlobalConfig();
  const saveProject = useSaveProjectConfig();

  const handleSaveGlobal = (data: Record<string, unknown>) => {
    saveGlobal.mutate(data, {
      onSuccess: () => toast.success("Global configuration saved"),
      onError: () => toast.error("Failed to save global configuration"),
    });
  };

  const handleSaveProject = (data: Record<string, unknown>) => {
    if (selectedProjectId == null) return;
    saveProject.mutate(
      { projectId: selectedProjectId, data },
      {
        onSuccess: () => toast.success("Project configuration saved"),
        onError: () => toast.error("Failed to save project configuration"),
      },
    );
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
      <Tabs defaultValue="global">
        <TabsList>
          <TabsTrigger value="global">Global</TabsTrigger>
          <TabsTrigger value="project">Project</TabsTrigger>
        </TabsList>
        <TabsContent value="global" className="mt-4">
          {globalConfig.isLoading ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : (
            <ConfigForm
              values={globalConfig.data ?? {}}
              onSave={handleSaveGlobal}
              saving={saveGlobal.isPending}
            />
          )}
        </TabsContent>
        <TabsContent value="project" className="mt-4">
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1 max-w-xs">
              <Label className="text-xs">Project</Label>
              <Select
                value={selectedProjectId != null ? String(selectedProjectId) : ""}
                onValueChange={(v) => setSelectedProjectId(Number(v))}
              >
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue placeholder="Select a project" />
                </SelectTrigger>
                <SelectContent>
                  {(projects.data ?? []).map((p) => (
                    <SelectItem key={p.id} value={String(p.id)}>
                      {p.display_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {selectedProjectId != null && projectConfig.isLoading && (
              <p className="text-sm text-muted-foreground">Loading...</p>
            )}
            {selectedProjectId != null && projectConfig.data && (
              <ConfigForm
                values={projectConfig.data.project}
                placeholders={projectConfig.data.merged}
                onSave={handleSaveProject}
                saving={saveProject.isPending}
              />
            )}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
