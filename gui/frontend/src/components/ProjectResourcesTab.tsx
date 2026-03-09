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
import { Skeleton } from "@/components/ui/skeleton";
import ResourceDetailSheet from "@/components/ResourceDetailSheet";
import InstallDialog from "@/components/InstallDialog";
import { Download } from "lucide-react";

const TYPE_LABELS: Record<string, string> = {
  roles: "Role",
  skills: "Skill",
  agents: "Agent",
  memories: "Memory",
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
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [selectedType, setSelectedType] = useState<string>("");
  const [sheetOpen, setSheetOpen] = useState(false);
  const [internalInstallOpen, setInternalInstallOpen] = useState(false);

  const installOpen = externalInstallOpen ?? internalInstallOpen;
  const setInstallOpen = externalOnInstallOpenChange ?? setInternalInstallOpen;

  const { data: detail } = useProjectResourceDetail(
    projectId,
    selectedType,
    selectedName ?? "",
    { enabled: sheetOpen && !!selectedName && !!selectedType },
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Resources installed to this project
        </p>
        <Button onClick={() => setInstallOpen(true)} size="sm">
          <Download className="mr-2 h-4 w-4" />
          Install
        </Button>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : !resources || resources.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center text-muted-foreground">
          No project resources installed yet.
        </div>
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Version</TableHead>
                  <TableHead>Description</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {resources.map((r) => (
                  <TableRow
                    key={`${r.type}-${r.name}`}
                    className="cursor-pointer"
                    onClick={() => {
                      setSelectedName(r.name);
                      setSelectedType(r.type);
                      setSheetOpen(true);
                    }}
                  >
                    <TableCell className="font-medium">{r.name}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-xs">
                        {TYPE_LABELS[r.type] ?? r.type}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {r.version ?? "—"}
                    </TableCell>
                    <TableCell className="max-w-[300px] truncate text-sm">
                      {r.description || "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
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
    </div>
  );
}
