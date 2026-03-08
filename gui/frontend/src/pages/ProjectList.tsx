import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import type { Project } from "../api/types";

export default function ProjectList() {
  const { data: projects, loading, error, refetch } = useApi<Project[]>("/projects");
  const [showForm, setShowForm] = useState(false);

  if (loading) return <p>Loading...</p>;
  if (error) return <p className="error">Error: {error}</p>;

  const list = projects ?? [];

  return (
    <div>
      <div className="page-header">
        <h1>Projects</h1>
        <button className="btn btn-primary" onClick={() => setShowForm(true)}>
          Register Project
        </button>
      </div>

      {showForm && (
        <RegisterForm
          onDone={() => {
            setShowForm(false);
            refetch();
          }}
          onCancel={() => setShowForm(false)}
        />
      )}

      {list.length === 0 ? (
        <p className="empty">No projects registered yet.</p>
      ) : (
        <table className="session-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Directory</th>
              <th>Created</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {list.map((p) => (
              <tr key={p.id}>
                <td>
                  <Link to={`/projects/${p.id}`}>{p.display_name}</Link>
                </td>
                <td className="cell-task">{p.working_dir}</td>
                <td>{formatDate(p.created_at)}</td>
                <td>
                  {p.dir_exists ? (
                    <span className="badge badge-success">OK</span>
                  ) : (
                    <span className="badge badge-warning">Missing</span>
                  )}
                </td>
                <td>
                  <DeleteButton projectId={p.id} onDeleted={refetch} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function RegisterForm({
  onDone,
  onCancel,
}: {
  onDone: () => void;
  onCancel: () => void;
}) {
  const [displayName, setDisplayName] = useState("");
  const [workingDir, setWorkingDir] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.post("/projects", {
        display_name: displayName.trim(),
        working_dir: workingDir.trim(),
      });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to register");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="inline-form" onSubmit={handleSubmit}>
      <div className="form-row">
        <label>
          Display Name
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            required
            autoFocus
          />
        </label>
        <label>
          Working Directory
          <input
            type="text"
            value={workingDir}
            onChange={(e) => setWorkingDir(e.target.value)}
            placeholder="/path/to/project"
            required
          />
        </label>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="form-actions">
        <button className="btn btn-primary" type="submit" disabled={submitting}>
          {submitting ? "Registering..." : "Register"}
        </button>
        <button className="btn" type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function DeleteButton({
  projectId,
  onDeleted,
}: {
  projectId: number;
  onDeleted: () => void;
}) {
  const [confirming, setConfirming] = useState(false);

  const handleDelete = async () => {
    try {
      await api.delete(`/projects/${projectId}`);
      onDeleted();
    } catch {
      // silently ignore — project may already be gone
    }
  };

  if (confirming) {
    return (
      <span className="confirm-group">
        <button className="btn btn-danger btn-sm" onClick={handleDelete}>
          Confirm
        </button>
        <button className="btn btn-sm" onClick={() => setConfirming(false)}>
          No
        </button>
      </span>
    );
  }

  return (
    <button className="btn btn-sm btn-ghost" onClick={() => setConfirming(true)}>
      Delete
    </button>
  );
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString();
  } catch {
    return iso;
  }
}
