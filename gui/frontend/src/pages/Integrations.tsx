import { useState } from "react";
import { useIntegrations, useIntegrationConfig } from "@/hooks/queries/use-integrations";
import { useStartIntegration, useStopIntegration, useSaveIntegrationConfig, useInstallIntegration, useUninstallIntegration } from "@/hooks/mutations/use-integrations";
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
import { CheckCircle2, Download, Play, Square, Settings2, ScrollText, Trash2, XCircle } from "lucide-react";
import { toast } from "sonner";
import type { Integration, IntegrationEnvField } from "@/api/types";
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
  const [configName, setConfigName] = useState<string | null>(null);
  const [logName, setLogName] = useState<string | null>(null);
  const [installOpen, setInstallOpen] = useState(false);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Integrations</h1>
          <p className="text-sm text-muted-foreground">
            Chat and community platform adapters
          </p>
        </div>
        <Button onClick={() => setInstallOpen(true)}>
          <Download className="mr-1.5 h-4 w-4" />
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
              <TableHead className="w-56" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {integrations.map((integration) => (
              <IntegrationRow
                key={integration.name}
                integration={integration}
                onConfigure={() => setConfigName(integration.name)}
                onLogs={() => setLogName(integration.name)}
              />
            ))}
          </TableBody>
        </Table>
      )}

      <InstallIntegrationDialog
        open={installOpen}
        onOpenChange={setInstallOpen}
      />

      <ConfigDialog
        name={configName}
        open={!!configName}
        onOpenChange={(open) => { if (!open) setConfigName(null); }}
      />

      <IntegrationLogSheet
        name={logName}
        open={!!logName}
        onOpenChange={(open) => { if (!open) setLogName(null); }}
      />
    </div>
  );
}

function IntegrationRow({
  integration,
  onConfigure,
  onLogs,
}: {
  integration: Integration;
  onConfigure: () => void;
  onLogs: () => void;
}) {
  const start = useStartIntegration();
  const stop = useStopIntegration();
  const uninstall = useUninstallIntegration();
  const isRunning = integration.status === "running";

  const handleStartStop = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (isRunning) {
      stop.mutate(integration.name, {
        onSuccess: () => toast.success(`Stopped ${integration.name}`),
        onError: (err) => toast.error(`Failed to stop: ${err.message}`),
      });
    } else {
      start.mutate(integration.name, {
        onSuccess: () => toast.success(`Started ${integration.name}`),
        onError: (err) => toast.error(`Failed to start: ${err.message}`),
      });
    }
  };

  const handleUninstall = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm(`Uninstall ${integration.name}? This will stop the adapter and remove all files.`)) return;
    uninstall.mutate(integration.name, {
      onSuccess: (res) => {
        if (res.exit_code === 0) {
          toast.success(`Uninstalled ${integration.name}`);
        } else {
          toast.error(`Uninstall failed: ${res.stderr || res.stdout}`);
        }
      },
      onError: (err) => toast.error(`Failed to uninstall: ${err.message}`),
    });
  };

  return (
    <TableRow>
      <TableCell className="font-medium">{integration.name}</TableCell>
      <TableCell className="max-w-[300px] truncate text-sm text-muted-foreground">
        {integration.description || "\u2014"}
      </TableCell>
      <TableCell>
        <div className="flex items-center gap-2">
          <StatusBadge status={integration.status} />
          {isRunning && (
            <span className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
          )}
        </div>
      </TableCell>
      <TableCell>
        <div className="flex items-center gap-1">
          <Button
            size="sm"
            variant={isRunning ? "destructive" : "default"}
            onClick={handleStartStop}
            disabled={start.isPending || stop.isPending}
          >
            {isRunning ? (
              <><Square className="mr-1 h-3.5 w-3.5" /> Stop</>
            ) : (
              <><Play className="mr-1 h-3.5 w-3.5" /> Start</>
            )}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={(e) => { e.stopPropagation(); onConfigure(); }}
          >
            <Settings2 className="h-3.5 w-3.5" />
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={(e) => { e.stopPropagation(); onLogs(); }}
          >
            <ScrollText className="h-3.5 w-3.5" />
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={handleUninstall}
            disabled={uninstall.isPending}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </TableCell>
    </TableRow>
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

function ConfigDialog({
  name,
  open,
  onOpenChange,
}: {
  name: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { data: config } = useIntegrationConfig(name ?? "", { enabled: open && !!name });
  const save = useSaveIntegrationConfig();
  const [values, setValues] = useState<Record<string, string>>({});
  const [initialized, setInitialized] = useState(false);

  // Initialize form values when config loads
  if (config && !initialized) {
    const initial: Record<string, string> = {};
    for (const key of Object.keys(config.env_schema)) {
      initial[key] = config.config_values[key] ?? "";
    }
    setValues(initial);
    setInitialized(true);
  }

  // Reset when dialog closes
  const handleOpenChange = (open: boolean) => {
    if (!open) {
      setInitialized(false);
      setValues({});
    }
    onOpenChange(open);
  };

  const handleSave = () => {
    if (!name) return;
    save.mutate(
      { name, config_values: values },
      {
        onSuccess: () => {
          toast.success("Configuration saved");
          handleOpenChange(false);
        },
        onError: (err) => toast.error(`Failed to save: ${err.message}`),
      },
    );
  };

  const schema = config?.env_schema ?? {};

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Configure {name}</DialogTitle>
          <DialogDescription>
            Set configuration values for this integration.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          {Object.entries(schema).map(([key, field]) => (
            <ConfigField
              key={key}
              name={key}
              field={field}
              value={values[key] ?? ""}
              onChange={(val) => setValues((prev) => ({ ...prev, [key]: val }))}
            />
          ))}
          {Object.keys(schema).length === 0 && (
            <p className="text-sm text-muted-foreground">
              This integration has no configuration options.
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={save.isPending}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ConfigField({
  name,
  field,
  value,
  onChange,
}: {
  name: string;
  field: IntegrationEnvField;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={`config-${name}`}>
        {name}
        {field.required && <span className="text-destructive ml-0.5">*</span>}
      </Label>
      <Input
        id={`config-${name}`}
        type="password"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={field.description}
      />
      {field.description && (
        <p className="text-xs text-muted-foreground">{field.description}</p>
      )}
    </div>
  );
}
