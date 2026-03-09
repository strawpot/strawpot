import { useState, useEffect } from "react";
import { useInstallResource } from "@/hooks/mutations/use-registry";
import { useInstallProjectResource } from "@/hooks/mutations/use-project-resources";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { CheckCircle2, XCircle } from "lucide-react";
import { toast } from "sonner";

const RESOURCE_TYPE_OPTIONS = [
  { value: "roles", label: "Role" },
  { value: "skills", label: "Skill" },
  { value: "agents", label: "Agent" },
  { value: "memories", label: "Memory" },
];

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultType?: string;
  projectId?: number;
}

type ResultState = { status: "success" | "error"; message: string } | null;

export default function InstallDialog({ open, onOpenChange, defaultType, projectId }: Props) {
  const [type, setType] = useState(defaultType ?? "roles");
  const [name, setName] = useState("");
  const [result, setResult] = useState<ResultState>(null);
  const [output, setOutput] = useState<string | null>(null);

  useEffect(() => {
    if (open && defaultType) setType(defaultType);
  }, [open, defaultType]);
  const globalInstall = useInstallResource();
  const projectInstall = useInstallProjectResource(projectId ?? 0);
  const install = projectId ? projectInstall : globalInstall;
  const isDone = result?.status === "success";

  const handleInstall = () => {
    if (!name.trim()) return;
    setResult(null);
    setOutput(null);
    install.mutate(
      { type, name: name.trim() },
      {
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
      },
    );
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
          <DialogTitle>{projectId ? "Install Resource to Project" : "Install Resource"}</DialogTitle>
          <DialogDescription>
            Install a resource from StrawHub by name.
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
            <Label htmlFor="install-type">Type</Label>
            <Select value={type} onValueChange={setType} disabled={isDone}>
              <SelectTrigger id="install-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {RESOURCE_TYPE_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="install-name">Package Name</Label>
            <Input
              id="install-name"
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. strawpot-claude-code"
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
          {result?.status === "success" ? (
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
