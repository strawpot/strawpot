import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import SessionTable from "../components/SessionTable";
import { useApi } from "../hooks/useApi";
import type { Project, Session } from "../api/types";

export default function ProjectDetail() {
  const { projectId } = useParams();
  const { data: project, loading: pLoading, error: pError } =
    useApi<Project>(`/projects/${projectId}`);
  const {
    data: sessions,
    loading: sLoading,
    error: sError,
    refetch,
  } = useApi<Session[]>(`/projects/${projectId}/sessions`);
  const [showLaunch, setShowLaunch] = useState(false);

  const loading = pLoading || sLoading;
  const error = pError || sError;

  if (loading) return <p>Loading...</p>;
  if (error) return <p className="error">Error: {error}</p>;
  if (!project) return <p className="error">Project not found</p>;

  const sessionList = sessions ?? [];

  return (
    <div>
      <div className="page-header">
        <h1>{project.display_name}</h1>
        <div className="page-header-actions">
          <button
            className="btn btn-primary"
            onClick={() => setShowLaunch(true)}
            disabled={!project.dir_exists}
          >
            Launch Session
          </button>
          <Link to="/projects" className="btn">
            Back to Projects
          </Link>
        </div>
      </div>

      <div className="project-info">
        <div className="project-info-row">
          <span className="project-info-label">Directory</span>
          <span className="project-info-value">{project.working_dir}</span>
          {project.dir_exists ? (
            <span className="badge badge-success">OK</span>
          ) : (
            <span className="badge badge-warning">Missing</span>
          )}
        </div>
        <div className="project-info-row">
          <span className="project-info-label">Created</span>
          <span className="project-info-value">
            {new Date(project.created_at).toLocaleString()}
          </span>
        </div>
      </div>

      {showLaunch && (
        <LaunchForm
          projectId={Number(projectId)}
          onLaunched={() => {
            setShowLaunch(false);
            refetch();
          }}
          onCancel={() => setShowLaunch(false)}
        />
      )}

      <section className="dashboard-section">
        <h2>Sessions ({sessionList.length})</h2>
        {sessionList.length === 0 ? (
          <p className="empty">No sessions yet.</p>
        ) : (
          <SessionTable sessions={sessionList} />
        )}
      </section>
    </div>
  );
}

interface ProjectConfig {
  merged: {
    orchestrator_role: string;
    runtime: string;
    isolation: string;
    merge_strategy: string;
    [key: string]: unknown;
  };
}

function LaunchForm({
  projectId,
  onLaunched,
  onCancel,
}: {
  projectId: number;
  onLaunched: () => void;
  onCancel: () => void;
}) {
  const navigate = useNavigate();
  const { data: config } = useApi<ProjectConfig>(
    `/projects/${projectId}/config`,
  );
  const { data: installedRoles } = useApi<string[]>("/roles");
  const defaults = config?.merged;

  const [task, setTask] = useState("");
  const [role, setRole] = useState("");
  const [showOverrides, setShowOverrides] = useState(false);
  const [runtime, setRuntime] = useState("");
  const [isolation, setIsolation] = useState("");
  const [mergeStrategy, setMergeStrategy] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        project_id: projectId,
        task: task.trim(),
      };
      if (role.trim()) body.role = role.trim();

      const overrides: Record<string, string> = {};
      if (runtime.trim()) overrides.runtime = runtime.trim();
      if (isolation.trim()) overrides.isolation = isolation.trim();
      if (mergeStrategy.trim()) overrides.merge_strategy = mergeStrategy.trim();
      if (Object.keys(overrides).length > 0) body.overrides = overrides;

      const result = await api.post<{ run_id: string }>("/sessions", body);
      onLaunched();
      navigate(`/projects/${projectId}/sessions/${result.run_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to launch");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="inline-form" onSubmit={handleSubmit}>
      <h3 style={{ marginBottom: "0.75rem" }}>Launch Session</h3>
      <div className="form-row">
        <label>
          Task <span className="required">*</span>
          <textarea
            value={task}
            onChange={(e) => setTask(e.target.value)}
            placeholder="Describe what the agent should do..."
            required
            autoFocus
            rows={3}
          />
        </label>
      </div>
      <div className="form-row">
        <label>
          Role
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
          >
            <option value="">
              {defaults?.orchestrator_role ?? "orchestrator"}
            </option>
            {(installedRoles ?? [])
              .filter((v) => v !== (defaults?.orchestrator_role ?? "orchestrator"))
              .map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
          </select>
        </label>
      </div>
      <div style={{ marginBottom: "0.75rem" }}>
        <button
          className="btn btn-sm"
          type="button"
          onClick={() => setShowOverrides(!showOverrides)}
        >
          {showOverrides ? "Hide" : "Show"} Advanced Options
        </button>
      </div>
      {showOverrides && (
        <div className="form-row">
          <label>
            Runtime
            <select
              value={runtime}
              onChange={(e) => setRuntime(e.target.value)}
            >
              <option value="">
                {defaults?.runtime ?? "claude_code"}
              </option>
              {["claude_code"]
                .filter((v) => v !== (defaults?.runtime ?? "claude_code"))
                .map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
            </select>
          </label>
          <label>
            Isolation
            <select
              value={isolation}
              onChange={(e) => setIsolation(e.target.value)}
            >
              <option value="">
                {defaults?.isolation ?? "none"}
              </option>
              {defaults?.isolation !== "none" && (
                <option value="none">none</option>
              )}
              {defaults?.isolation !== "worktree" && (
                <option value="worktree">worktree</option>
              )}
            </select>
          </label>
          <label>
            Merge Strategy
            <select
              value={mergeStrategy}
              onChange={(e) => setMergeStrategy(e.target.value)}
            >
              <option value="">
                {defaults?.merge_strategy ?? "auto"}
              </option>
              {["auto", "local", "pr"]
                .filter((v) => v !== (defaults?.merge_strategy ?? "auto"))
                .map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
            </select>
          </label>
        </div>
      )}
      {error && <p className="error">{error}</p>}
      <div className="form-actions">
        <button className="btn btn-primary" type="submit" disabled={submitting}>
          {submitting ? "Launching..." : "Launch"}
        </button>
        <button className="btn" type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
