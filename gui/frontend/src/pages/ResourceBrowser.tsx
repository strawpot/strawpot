import { useState } from "react";
import { useParams } from "react-router-dom";
import { useResources, useResourceDetail } from "@/hooks/queries/use-registry";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  roles: "Roles",
  skills: "Skills",
  agents: "Agents",
  memories: "Memory Providers",
};

export default function ResourceBrowser() {
  const { resourceType = "roles" } = useParams<{ resourceType: string }>();
  const { data: resources, isLoading } = useResources(resourceType);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [installOpen, setInstallOpen] = useState(false);

  const { data: detail } = useResourceDetail(resourceType, selectedName ?? "", {
    enabled: sheetOpen && !!selectedName,
  });

  const label = TYPE_LABELS[resourceType] ?? resourceType;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{label}</h1>
          <p className="text-sm text-muted-foreground">
            Installed {label.toLowerCase()} from StrawHub
          </p>
        </div>
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
          No {label.toLowerCase()} installed yet.
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Version</TableHead>
              <TableHead>Description</TableHead>
              <TableHead>Source</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {resources.map((r) => (
              <TableRow
                key={r.name}
                className="cursor-pointer"
                onClick={() => {
                  setSelectedName(r.name);
                  setSheetOpen(true);
                }}
              >
                <TableCell className="font-medium">{r.name}</TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {r.version ?? "—"}
                </TableCell>
                <TableCell className="max-w-[300px] truncate text-sm">
                  {r.description || "—"}
                </TableCell>
                <TableCell>
                  <Badge variant="outline" className="text-xs">
                    {r.source}
                  </Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <ResourceDetailSheet
        resource={detail ?? null}
        resourceType={resourceType}
        open={sheetOpen}
        onOpenChange={setSheetOpen}
      />

      <InstallDialog
        open={installOpen}
        onOpenChange={setInstallOpen}
        defaultType={resourceType}
      />
    </div>
  );
}
