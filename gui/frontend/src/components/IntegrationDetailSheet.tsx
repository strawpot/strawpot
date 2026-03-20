import { useState } from "react";
import type { Integration, IntegrationEnvField } from "@/api/types";
import { useIntegrationConfig } from "@/hooks/queries/use-integrations";
import {
  useStartIntegration,
  useStopIntegration,
  useSaveIntegrationConfig,
  useSetAutoStart,
  useUpdateIntegration,
  useReinstallIntegration,
  useUninstallIntegration,
} from "@/hooks/mutations/use-integrations";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Switch } from "@/components/ui/switch";
import { Eye, EyeOff, Play, Square } from "lucide-react";
import { toast } from "sonner";

interface Props {
  integration: Integration | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onLogs: (name: string, projectId: number) => void;
}

export default function IntegrationDetailSheet({
  integration,
  open,
  onOpenChange,
  onLogs,
}: Props) {
  const start = useStartIntegration();
  const stop = useStopIntegration();
  const setAutoStart = useSetAutoStart();
  const update = useUpdateIntegration();
  const reinstall = useReinstallIntegration();
  const uninstall = useUninstallIntegration();
  const [confirming, setConfirming] = useState(false);

  if (!integration) return null;

  const isRunning = integration.status === "running";
  const actionPending =
    update.isPending || reinstall.isPending || uninstall.isPending;

  const ref = { name: integration.name, projectId: integration.project_id };

  const handleStartStop = () => {
    if (isRunning) {
      stop.mutate(ref, {
        onSuccess: () => toast.success(`Stopped ${integration.name}`),
        onError: (err) => toast.error(`Failed to stop: ${err.message}`),
      });
    } else {
      start.mutate(ref, {
        onSuccess: () => toast.success(`Started ${integration.name}`),
        onError: (err) => toast.error(`Failed to start: ${err.message}`),
      });
    }
  };

  const handleUpdate = () => {
    update.mutate(ref, {
      onSuccess: (res) => {
        if (res.exit_code === 0) toast.success(`Updated ${integration.name}`);
        else toast.error(`Update failed: ${res.stderr || res.stdout}`);
      },
      onError: (err) => toast.error(`Failed to update: ${err.message}`),
    });
  };

  const handleReinstall = () => {
    reinstall.mutate(ref, {
      onSuccess: (res) => {
        if (res.exit_code === 0)
          toast.success(`Reinstalled ${integration.name}`);
        else toast.error(`Reinstall failed: ${res.stderr || res.stdout}`);
      },
      onError: (err) => toast.error(`Failed to reinstall: ${err.message}`),
    });
  };

  const handleUninstall = () => {
    if (!confirming) {
      setConfirming(true);
      return;
    }
    uninstall.mutate(ref, {
      onSuccess: (res) => {
        if (res.exit_code === 0) {
          toast.success(`Uninstalled ${integration.name}`);
          onOpenChange(false);
        } else {
          toast.error(`Uninstall failed: ${res.stderr || res.stdout}`);
        }
        setConfirming(false);
      },
      onError: (err) => {
        toast.error(`Failed to uninstall: ${err.message}`);
        setConfirming(false);
      },
    });
  };

  return (
    <Sheet
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v);
        setConfirming(false);
      }}
    >
      <SheetContent
        side="right"
        className="flex h-full flex-col sm:max-w-xl overflow-x-hidden"
      >
        <SheetHeader className="shrink-0">
          <SheetTitle className="flex items-center gap-2">
            {integration.name}
            <StatusBadge status={integration.status} />
            {isRunning && (
              <span className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
            )}
          </SheetTitle>
          <SheetDescription>
            {integration.description || "No description"}
          </SheetDescription>
        </SheetHeader>

        <div className="shrink-0 flex flex-col gap-4 px-4">
          <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
            <span>
              Path:{" "}
              <code className="rounded bg-muted px-1">{integration.path}</code>
            </span>
            {integration.started_at && (
              <span>
                Started:{" "}
                <strong>
                  {new Date(integration.started_at).toLocaleString()}
                </strong>
              </span>
            )}
            {integration.pid && (
              <span>
                PID: <strong>{integration.pid}</strong>
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Switch
              id="auto-start"
              checked={integration.auto_start}
              onCheckedChange={(checked) => {
                setAutoStart.mutate(
                  { ...ref, enabled: checked },
                  {
                    onSuccess: () =>
                      toast.success(
                        checked ? "Auto-start enabled" : "Auto-start disabled"
                      ),
                    onError: (err) =>
                      toast.error(`Failed to update: ${err.message}`),
                  }
                );
              }}
              disabled={setAutoStart.isPending}
            />
            <Label htmlFor="auto-start" className="text-xs">
              Start automatically when StrawPot launches
            </Label>
          </div>
          {integration.last_error && (
            <div className="rounded-md bg-destructive/10 p-3 text-xs text-destructive">
              {integration.last_error}
            </div>
          )}
        </div>

        <ScrollArea className="min-h-0 flex-1">
          <div className="px-4 space-y-6">
            <ConfigSection
              name={integration.name}
              projectId={integration.project_id}
              enabled={open}
            />
          </div>
        </ScrollArea>

        <div className="shrink-0 border-t border-border p-4 flex gap-2">
          <Button
            size="sm"
            variant={isRunning ? "destructive" : "default"}
            onClick={handleStartStop}
            disabled={start.isPending || stop.isPending}
          >
            {isRunning ? (
              <>
                <Square className="mr-1 h-3.5 w-3.5" /> Stop
              </>
            ) : (
              <>
                <Play className="mr-1 h-3.5 w-3.5" /> Start
              </>
            )}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => onLogs(integration.name, integration.project_id)}
          >
            Logs
          </Button>
          <Button size="sm" variant="outline" onClick={handleUpdate} disabled={actionPending}>
            {update.isPending ? "Updating..." : "Update"}
          </Button>
          <Button size="sm" variant="outline" onClick={handleReinstall} disabled={actionPending}>
            {reinstall.isPending ? "Reinstalling..." : "Reinstall"}
          </Button>
          <div className="flex-1" />
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
        </div>
      </SheetContent>
    </Sheet>
  );
}

function StatusBadge({ status }: { status: string }) {
  const variants: Record<
    string,
    { variant: "default" | "secondary" | "destructive" | "outline"; label: string }
  > = {
    running: { variant: "default", label: "Running" },
    stopped: { variant: "secondary", label: "Stopped" },
    error: { variant: "destructive", label: "Error" },
  };
  const { variant, label } = variants[status] ?? {
    variant: "outline" as const,
    label: status,
  };
  return <Badge variant={variant}>{label}</Badge>;
}

function ConfigSection({
  name,
  projectId,
  enabled,
}: {
  name: string;
  projectId?: number;
  enabled: boolean;
}) {
  const { data: config } = useIntegrationConfig(name, { enabled, projectId });
  const save = useSaveIntegrationConfig();
  const [values, setValues] = useState<Record<string, string>>({});
  const [initialized, setInitialized] = useState(false);

  if (config && !initialized) {
    const initial: Record<string, string> = {};
    for (const key of Object.keys(config.env_schema)) {
      initial[key] = config.config_values[key] ?? "";
    }
    setValues(initial);
    setInitialized(true);
  }

  const schema = config?.env_schema ?? {};
  if (Object.keys(schema).length === 0) return null;

  const handleSave = () => {
    save.mutate(
      { name, projectId, config_values: values },
      {
        onSuccess: () => toast.success("Configuration saved"),
        onError: (err) => toast.error(`Failed to save: ${err.message}`),
      },
    );
  };

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-medium">Configuration</h3>
      {Object.entries(schema).map(([key, field]) => (
        <ConfigField
          key={key}
          name={key}
          field={field}
          value={values[key] ?? ""}
          onChange={(val) => setValues((prev) => ({ ...prev, [key]: val }))}
        />
      ))}
      <Button size="sm" onClick={handleSave} disabled={save.isPending}>
        {save.isPending ? "Saving..." : "Save Configuration"}
      </Button>
    </div>
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
  const [visible, setVisible] = useState(false);
  return (
    <div className="space-y-1.5">
      <Label htmlFor={`config-${name}`}>
        {name}
        {field.required && <span className="text-destructive ml-0.5">*</span>}
      </Label>
      <div className="relative">
        <Input
          id={`config-${name}`}
          type={visible ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.description}
          className="pr-8"
        />
        <button
          type="button"
          className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          onClick={() => setVisible((v) => !v)}
        >
          {visible ? (
            <EyeOff className="h-3.5 w-3.5" />
          ) : (
            <Eye className="h-3.5 w-3.5" />
          )}
        </button>
      </div>
      {field.description && (
        <p className="text-xs text-muted-foreground">{field.description}</p>
      )}
    </div>
  );
}
