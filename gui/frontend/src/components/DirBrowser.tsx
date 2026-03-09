import { useEffect, useState } from "react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Folder, FolderUp } from "lucide-react";

interface DirEntry {
  name: string;
  path: string;
}

interface BrowseResult {
  path: string;
  parent: string | null;
  entries: DirEntry[];
}

export default function DirBrowser({
  initialPath,
  onSelect,
  onCancel,
}: {
  initialPath?: string;
  onSelect: (path: string) => void;
  onCancel: () => void;
}) {
  const [current, setCurrent] = useState<BrowseResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newFolderName, setNewFolderName] = useState<string | null>(null);

  const browse = (path?: string) => {
    setLoading(true);
    setError(null);
    const query = path ? `?path=${encodeURIComponent(path)}` : "";
    api
      .get<BrowseResult>(`/fs/browse${query}`)
      .then(setCurrent)
      .catch((err) => setError(err.message ?? "Failed to browse"))
      .finally(() => setLoading(false));
  };

  const createFolder = async () => {
    if (!current || !newFolderName?.trim()) return;
    try {
      const result = await api.post<{ path: string }>("/fs/mkdir", {
        path: current.path,
        name: newFolderName.trim(),
      });
      setNewFolderName(null);
      browse(result.path);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create folder");
    }
  };

  useEffect(() => {
    browse(initialPath || undefined);
  }, []);

  return (
    <Dialog open onOpenChange={(open) => !open && onCancel()}>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>Select Directory</DialogTitle>
        </DialogHeader>

        {current && (
          <div className="break-all rounded-md bg-muted px-3 py-1.5 font-mono text-xs">
            {current.path}
          </div>
        )}

        {error && <p className="text-sm text-destructive">{error}</p>}

        {loading && !current ? (
          <p className="py-4 text-sm text-muted-foreground">Loading...</p>
        ) : (
          <ScrollArea className="h-[300px]">
            <div className="space-y-0.5">
              {current?.parent && (
                <button
                  className="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-sm text-primary hover:bg-accent"
                  onClick={() => browse(current.parent!)}
                >
                  <FolderUp className="h-4 w-4" />
                  ..
                </button>
              )}
              {current?.entries.map((e) => (
                <button
                  key={e.path}
                  className="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-sm text-primary hover:bg-accent"
                  onClick={() => browse(e.path)}
                >
                  <Folder className="h-4 w-4" />
                  {e.name}
                </button>
              ))}
              {current?.entries.length === 0 && (
                <p className="px-3 py-4 text-sm italic text-muted-foreground">
                  No subdirectories
                </p>
              )}
            </div>
          </ScrollArea>
        )}

        <DialogFooter>
          {newFolderName !== null ? (
            <div className="flex w-full gap-2">
              <Input
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") createFolder();
                  if (e.key === "Escape") setNewFolderName(null);
                }}
                placeholder="Folder name"
                autoFocus
                className="flex-1"
              />
              <Button size="sm" onClick={createFolder}>
                Create
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setNewFolderName(null)}
              >
                Cancel
              </Button>
            </div>
          ) : (
            <>
              <Button
                variant="outline"
                onClick={() => setNewFolderName("")}
                disabled={!current}
              >
                New Folder
              </Button>
              <div className="flex-1" />
              <Button
                onClick={() => current && onSelect(current.path)}
                disabled={!current}
              >
                Select
              </Button>
              <Button variant="outline" onClick={onCancel}>
                Cancel
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
