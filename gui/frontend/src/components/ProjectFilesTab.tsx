import { useCallback, useRef, useState } from "react";
import { useProjectFiles } from "@/hooks/queries/use-projects";
import {
  useUploadProjectFiles,
  useDeleteProjectFile,
} from "@/hooks/mutations/use-projects";
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
import { toast } from "sonner";
import { Trash2, Upload } from "lucide-react";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function ProjectFilesTab({
  projectId,
}: {
  projectId: number;
}) {
  const files = useProjectFiles(projectId);
  const upload = useUploadProjectFiles();
  const deleteFile = useDeleteProjectFile();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const handleFiles = useCallback(
    (fileList: FileList | File[]) => {
      const arr = Array.from(fileList);
      if (arr.length === 0) return;
      upload.mutate(
        { projectId, files: arr },
        {
          onSuccess: () => toast.success(`Uploaded ${arr.length} file(s)`),
          onError: () => toast.error("Upload failed"),
        },
      );
    },
    [projectId, upload],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles],
  );

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const onDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
  }, []);

  const onBrowse = useCallback(() => {
    inputRef.current?.click();
  }, []);

  const onInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files) {
        handleFiles(e.target.files);
        e.target.value = "";
      }
    },
    [handleFiles],
  );

  const handleDelete = useCallback(
    (filePath: string) => {
      deleteFile.mutate(
        { projectId, filePath },
        {
          onSuccess: () => toast.success("File deleted"),
          onError: () => toast.error("Failed to delete file"),
        },
      );
    },
    [projectId, deleteFile],
  );

  const fileList = files.data ?? [];

  return (
    <div className="space-y-4">
      <div
        onDrop={onDrop}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        className={`flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-8 transition-colors ${
          dragOver
            ? "border-primary bg-primary/5"
            : "border-muted-foreground/25"
        }`}
      >
        <Upload className="h-8 w-8 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">
          Drag & drop files here, or{" "}
          <button
            type="button"
            onClick={onBrowse}
            className="font-medium text-primary underline-offset-4 hover:underline"
          >
            browse
          </button>
        </p>
        {upload.isPending && (
          <p className="text-xs text-muted-foreground">Uploading...</p>
        )}
        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          onChange={onInputChange}
        />
      </div>

      {fileList.length === 0 ? (
        <p className="text-sm italic text-muted-foreground">
          No files uploaded yet.
        </p>
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead className="w-24">Size</TableHead>
                  <TableHead className="w-44">Modified</TableHead>
                  <TableHead className="w-12" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {fileList.map((f) => (
                  <TableRow key={f.path}>
                    <TableCell className="font-mono text-xs">
                      {f.path}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {formatSize(f.size)}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(f.modified_at).toLocaleString()}
                    </TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        onClick={() => handleDelete(f.path)}
                        disabled={deleteFile.isPending}
                      >
                        <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
