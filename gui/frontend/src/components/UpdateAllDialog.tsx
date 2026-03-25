import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { CheckCircle2, XCircle, Loader2, RefreshCw } from "lucide-react";
import type { InstallResult } from "@/api/types";

type Status = "idle" | "running" | "done" | "error";

interface UpdateLine {
  text: string;
  updated: boolean;
}

function parseOutput(stdout: string): { lines: UpdateLine[]; updated: number; upToDate: number } {
  const lines: UpdateLine[] = stdout
    .split("\n")
    .map((raw) => raw.trim())
    .filter(Boolean)
    .filter((text) => !text.match(/^No\b.*\bpackages to update/))
    .map((text) => ({ text, updated: !text.includes("already up to date") }));

  const updated = lines.filter((l) => l.updated).length;
  return { lines, updated, upToDate: lines.length - updated };
}

const TYPE_LABELS: Record<string, string> = {
  roles: "Roles",
  skills: "Skills",
  agents: "Agents",
  memories: "Memory Providers",
};

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdate: () => Promise<InstallResult>;
  scope: string; // e.g. "global" or project name
  resourceType?: string; // e.g. "roles", "skills" — omit to update all types
}

export default function UpdateAllDialog({ open, onOpenChange, onUpdate, scope, resourceType }: Props) {
  const [status, setStatus] = useState<Status>("idle");
  const [result, setResult] = useState<InstallResult | null>(null);

  const parsed = result ? parseOutput(result.stdout) : null;
  const errorOutput = result?.stderr?.trim() || result?.stdout?.trim() || "Unknown error";

  const handleUpdate = async () => {
    setStatus("running");
    setResult(null);
    try {
      const res = await onUpdate();
      setResult(res);
      setStatus(res.exit_code === 0 ? "done" : "error");
    } catch (err) {
      setResult({
        exit_code: -1,
        stdout: "",
        stderr: err instanceof Error ? err.message : String(err),
      });
      setStatus("error");
    }
  };

  const handleClose = () => {
    setStatus("idle");
    setResult(null);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={status === "running" ? undefined : handleClose}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            Update All {resourceType ? TYPE_LABELS[resourceType] ?? resourceType : "Resources"}
          </DialogTitle>
          <DialogDescription>
            {status === "idle" &&
              `Update all installed ${resourceType ? (TYPE_LABELS[resourceType] ?? resourceType).toLowerCase() : "resources"} (${scope}) to their latest versions.`}
            {status === "running" && "Updating resources..."}
            {status === "done" &&
              parsed &&
              (parsed.updated === 0 && parsed.upToDate === 0
                ? `No ${resourceType ? (TYPE_LABELS[resourceType] ?? resourceType).toLowerCase() : "resources"} packages to update.`
                : `${parsed.updated} updated, ${parsed.upToDate} already up to date.`)}
            {status === "error" && "Update failed."}
          </DialogDescription>
        </DialogHeader>

        {status === "running" && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        )}

        {status === "done" && parsed && parsed.lines.length > 0 && (
          <ScrollArea className="max-h-64 rounded-md border p-3">
            <div className="space-y-1 text-sm font-mono">
              {parsed.lines.map((line, i) => (
                <div key={i} className="flex items-start gap-2">
                  {line.updated ? (
                    <RefreshCw className="mt-0.5 h-3.5 w-3.5 shrink-0 text-blue-500" />
                  ) : (
                    <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-green-500" />
                  )}
                  <span className={line.updated ? "text-foreground" : "text-muted-foreground"}>
                    {line.text}
                  </span>
                </div>
              ))}
            </div>
          </ScrollArea>
        )}

        {status === "error" && (
          <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3">
            <div className="flex items-start gap-2">
              <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
              <pre className="whitespace-pre-wrap text-sm text-destructive">{errorOutput}</pre>
            </div>
          </div>
        )}

        <DialogFooter>
          {status === "idle" && (
            <>
              <Button variant="outline" onClick={handleClose}>
                Cancel
              </Button>
              <Button onClick={handleUpdate}>
                <RefreshCw className="mr-2 h-4 w-4" />
                Update All{resourceType ? ` ${TYPE_LABELS[resourceType] ?? resourceType}` : ""}
              </Button>
            </>
          )}
          {status === "running" && (
            <Button disabled>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Updating...
            </Button>
          )}
          {(status === "done" || status === "error") && (
            <Button onClick={handleClose}>Close</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
