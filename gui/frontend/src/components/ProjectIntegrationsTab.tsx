import { useState } from "react";
import { useIntegrations } from "@/hooks/queries/use-integrations";
import { Badge } from "@/components/ui/badge";
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
import type { Integration } from "@/api/types";
import IntegrationDetailSheet from "@/components/IntegrationDetailSheet";
import IntegrationLogSheet from "@/components/IntegrationLogSheet";

function StatusBadge({ status }: { status: string }) {
  const variants: Record<string, { variant: "default" | "secondary" | "destructive" | "outline"; label: string }> = {
    running: { variant: "default", label: "Running" },
    stopped: { variant: "secondary", label: "Stopped" },
    error: { variant: "destructive", label: "Error" },
  };
  const { variant, label } = variants[status] ?? { variant: "outline" as const, label: status };
  return <Badge variant={variant}>{label}</Badge>;
}

interface Props {
  projectId: number;
}

export default function ProjectIntegrationsTab({ projectId }: Props) {
  const { data: integrations, isLoading } = useIntegrations(projectId);
  const [selected, setSelected] = useState<Integration | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [logName, setLogName] = useState<string | null>(null);
  const [logProjectId, setLogProjectId] = useState<number | undefined>(undefined);

  const integrationList = integrations ?? [];

  const currentSelected = selected
    ? integrationList.find(
        (i) => i.name === selected.name && i.project_id === selected.project_id,
      ) ?? selected
    : null;

  return (
    <div className="space-y-4">
      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      ) : integrationList.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center text-muted-foreground">
          <p>No integrations installed yet.</p>
          <p className="mt-1 text-xs">
            Install an integration from Strawhub to get started.
          </p>
        </div>
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Version</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {integrationList.map((integration) => (
                  <TableRow
                    key={integration.name}
                    className="cursor-pointer"
                    onClick={() => {
                      setSelected(integration);
                      setSheetOpen(true);
                    }}
                  >
                    <TableCell className="font-medium">{integration.name}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {integration.version ? `v${integration.version}` : "\u2014"}
                    </TableCell>
                    <TableCell className="max-w-[300px] truncate text-sm text-muted-foreground">
                      {integration.description || "\u2014"}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <StatusBadge status={integration.status} />
                        {integration.status === "running" && (
                          <span className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <IntegrationDetailSheet
        integration={currentSelected}
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        onLogs={(name, pid) => { setLogName(name); setLogProjectId(pid); }}
      />

      <IntegrationLogSheet
        name={logName}
        projectId={logProjectId}
        open={!!logName}
        onOpenChange={(open) => { if (!open) setLogName(null); }}
      />

    </div>
  );
}
