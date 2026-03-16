import { useState } from "react";
import { useIntegrations } from "@/hooks/queries/use-integrations";
import { useInstallIntegration } from "@/hooks/mutations/use-integrations";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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

export default function Integrations() {
  const { data: integrations, isLoading } = useIntegrations();
  const [selected, setSelected] = useState<Integration | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [logName, setLogName] = useState<string | null>(null);
  const [installOpen, setInstallOpen] = useState(false);

  // Keep selected integration up-to-date from the list query
  const currentSelected = selected
    ? integrations?.find((i) => i.name === selected.name) ?? selected
    : null;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Integrations</h1>
          <p className="text-sm text-muted-foreground">
            Chat and community platform adapters
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
      ) : !integrations || integrations.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border p-8 text-center text-muted-foreground">
          <p>No integrations installed yet.</p>
          <p className="mt-1 text-xs">
            Install from Strawhub or place adapter directories in <code className="rounded bg-muted px-1">~/.strawpot/integrations/</code>
          </p>
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Description</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {integrations.map((integration) => (
              <TableRow
                key={integration.name}
                className="cursor-pointer"
                onClick={() => {
                  setSelected(integration);
                  setSheetOpen(true);
                }}
              >
                <TableCell className="font-medium">{integration.name}</TableCell>
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
      )}

      <IntegrationDetailSheet
        integration={currentSelected}
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        onLogs={(name) => setLogName(name)}
      />

      <IntegrationLogSheet
        name={logName}
        open={!!logName}
        onOpenChange={(open) => { if (!open) setLogName(null); }}
      />

      <InstallIntegrationDialog
        open={installOpen}
        onOpenChange={setInstallOpen}
      />
    </div>
  );
}

function InstallIntegrationDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
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
    install.mutate(name.trim(), {
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
            Install a chat adapter from Strawhub by name.
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
            <Label htmlFor="install-integration-name">Package Name</Label>
            <Input
              id="install-integration-name"
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
