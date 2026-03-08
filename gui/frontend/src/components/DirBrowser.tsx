import { useEffect, useState } from "react";
import { api } from "../api/client";

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
    <div className="modal-overlay" onClick={onCancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>Select Directory</h3>
          <button className="btn btn-sm btn-ghost" onClick={onCancel}>
            &times;
          </button>
        </div>
        <div className="dir-browser-path">{current?.path}</div>
        {error && <p className="error" style={{ padding: "0.5rem 1rem" }}>{error}</p>}
        {loading && !current ? (
          <p style={{ padding: "1rem" }}>Loading...</p>
        ) : (
          <ul className="dir-browser-list">
            {current?.parent && (
              <li>
                <button
                  className="dir-entry"
                  onClick={() => browse(current.parent!)}
                >
                  ..
                </button>
              </li>
            )}
            {current?.entries.map((e) => (
              <li key={e.path}>
                <button className="dir-entry" onClick={() => browse(e.path)}>
                  {e.name}
                </button>
              </li>
            ))}
            {current?.entries.length === 0 && (
              <li className="empty" style={{ padding: "0.75rem" }}>
                No subdirectories
              </li>
            )}
          </ul>
        )}
        <div className="modal-footer">
          {newFolderName !== null ? (
            <div className="input-with-button" style={{ flex: 1 }}>
              <input
                type="text"
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") createFolder();
                  if (e.key === "Escape") setNewFolderName(null);
                }}
                placeholder="Folder name"
                autoFocus
              />
              <button className="btn btn-primary btn-sm" onClick={createFolder}>
                Create
              </button>
              <button className="btn btn-sm" onClick={() => setNewFolderName(null)}>
                Cancel
              </button>
            </div>
          ) : (
            <>
              <button
                className="btn"
                onClick={() => setNewFolderName("")}
                disabled={!current}
              >
                New Folder
              </button>
              <div style={{ flex: 1 }} />
              <button
                className="btn btn-primary"
                onClick={() => current && onSelect(current.path)}
                disabled={!current}
              >
                Select
              </button>
              <button className="btn" onClick={onCancel}>
                Cancel
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
