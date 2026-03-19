import { useState } from "react";
import { useIntegrations } from "@/hooks/queries/use-integrations";
import { useInstallIntegration } from "@/hooks/mutations/use-integrations";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { CheckCircle2, Download, XCircle } from "lucide-react";
import { toast } from "sonner";
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
  const [installOpen, setInstallOpen] = useState(false);

  const integrationList = integrations ?? [];

  const currentSelected = selected
    ? integrationList.find(
        (i) => i.name === selected.name && i.project_id === selected.project_id,
      ) ?? selected
    : null;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Integrations installed in this project
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

      <InstallProjectIntegrationDialog
        open={installOpen}
        onOpenChange={setInstallOpen}
        projectId={projectId}
      />
    </div>
  );
}

function InstallProjectIntegrationDialog({
  open,
  onOpenChange,
  projectId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: number;
}) {
  const install = useInstallIntegration();
  const [name, setName] = useState("");
  const [result, setResult] = useState<{ status: "success" | "error"; message: string } | null>(null);
  const [output, setOutput] = useState<string | null>(null);
  const isDone = result?.status === "success";

  const handleInstall = () => {
    if (!name.trim()) return;
    setResult(null);
    setOutput(null);
    install.mutate({ name: name.trim(), projectId }, {
      onSuccess: (res) => {
        if (res.exit_code === 0) {
          toast.success(`Installed ${name.trim()}`);
          setResult({ status: "success", message: `Successfully installed ${name.trim()}` });
          setOutput(res.stdout || null);
        } else {
          setResult({ status: "error", message: "Installation failed" });
          setOutput(res.stderr || res.stdout || "Unknown error.");
        }
      },
      onError: () => {
        setResult({ status: "error", message: "Install request failed" });
        toast.error("Install request failed");
      },
    });
  };

  const handleClose = (v: boolean) => {
    if (!v) {
      setResult(null);
      setOutput(null);
      setName("");
    }
    onOpenChange(v);
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Install Integration</DialogTitle>
          <DialogDescription>
            Install a chat adapter for this project from Strawhub by name.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          {result && (
            <Alert variant={result.status === "error" ? "destructive" : "default"} className={result.status === "success" ? "border-green-200 bg-green-50 text-green-800 dark:border-green-800 dark:bg-green-950 dark:text-green-300" : ""}>
              {result.status === "success" ? (
                <CheckCircle2 className="h-4 w-4 text-green-600 dark:text-green-400" />
              ) : (
                <XCircle className="h-4 w-4" />
              )}
              <AlertTitle>{result.status === "success" ? "Installed" : "Error"}</AlertTitle>
              <AlertDescription>{result.message}</AlertDescription>
            </Alert>
          )}
          <div className="flex flex-col gap-2">
            <Label htmlFor="install-project-integration-name">Package Name</Label>
            <Input
              id="install-project-integration-name"
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. telegram"
              readOnly={isDone}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleInstall();
              }}
            />
          </div>
          {output && (
            <details className="text-sm">
              <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
                Output
              </summary>
              <pre className="mt-2 max-h-40 overflow-auto rounded-md bg-muted p-3 text-xs">
                {output}
              </pre>
            </details>
          )}
        </div>
        <DialogFooter>
          {isDone ? (
            <Button onClick={() => handleClose(false)}>
              Done
            </Button>
          ) : (
            <Button
              onClick={handleInstall}
              disabled={!name.trim() || install.isPending}
            >
              {install.isPending ? "Installing..." : "Install"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
