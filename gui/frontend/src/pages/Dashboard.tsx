import { Link } from "react-router-dom";
import { useApi } from "../hooks/useApi";
import type { Project, Session, SessionList } from "../api/types";

export default function Dashboard() {
  const projects = useApi<Project[]>("/projects");
  const running = useApi<SessionList>("/sessions?status=running&per_page=50");
  const recent = useApi<SessionList>(
    "/sessions?per_page=10",
  );

  const loading = projects.loading || running.loading || recent.loading;
  const error = projects.error || running.error || recent.error;

  if (loading) return <p>Loading...</p>;
  if (error) return <p className="error">Error: {error}</p>;

  const projectList = projects.data ?? [];
  const runningSessions = running.data?.items ?? [];
  const recentSessions = recent.data?.items ?? [];

  // Count running sessions per project
  const runningByProject = new Map<number, number>();
  for (const s of runningSessions) {
    runningByProject.set(s.project_id, (runningByProject.get(s.project_id) ?? 0) + 1);
  }

  return (
    <div className="dashboard">
      <h1>Dashboard</h1>

      <section className="dashboard-section">
        <h2>Projects ({projectList.length})</h2>
        {projectList.length === 0 ? (
          <p className="empty">No projects registered.</p>
        ) : (
          <div className="card-grid">
            {projectList.map((p) => (
              <Link
                key={p.id}
                to={`/projects/${p.id}`}
                className="card"
              >
                <div className="card-title">{p.display_name}</div>
                <div className="card-meta">{p.working_dir}</div>
                {!p.dir_exists && (
                  <span className="badge badge-warning">Directory missing</span>
                )}
                {(runningByProject.get(p.id) ?? 0) > 0 && (
                  <span className="badge badge-running">
                    {runningByProject.get(p.id)} running
                  </span>
                )}
              </Link>
            ))}
          </div>
        )}
      </section>

      {runningSessions.length > 0 && (
        <section className="dashboard-section">
          <h2>Running Sessions ({runningSessions.length})</h2>
          <SessionTable sessions={runningSessions} />
        </section>
      )}

      <section className="dashboard-section">
        <h2>Recent Sessions</h2>
        {recentSessions.length === 0 ? (
          <p className="empty">No sessions yet.</p>
        ) : (
          <SessionTable sessions={recentSessions} />
        )}
      </section>
    </div>
  );
}

function SessionTable({ sessions }: { sessions: Session[] }) {
  return (
    <table className="session-table">
      <thead>
        <tr>
          <th>Run ID</th>
          <th>Role</th>
          <th>Status</th>
          <th>Started</th>
          <th>Duration</th>
          <th>Task</th>
        </tr>
      </thead>
      <tbody>
        {sessions.map((s) => (
          <tr key={s.run_id}>
            <td>
              <Link to={`/projects/${s.project_id}/sessions/${s.run_id}`}>
                {s.run_id.slice(0, 16)}
              </Link>
            </td>
            <td>{s.role}</td>
            <td>
              <span className={`badge badge-${statusColor(s.status)}`}>
                {s.status}
              </span>
            </td>
            <td>{formatTime(s.started_at)}</td>
            <td>{formatDuration(s.duration_ms)}</td>
            <td className="cell-task">{s.task ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function statusColor(status: string): string {
  switch (status) {
    case "running":
    case "starting":
      return "running";
    case "completed":
      return "success";
    case "failed":
      return "error";
    default:
      return "default";
  }
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function formatDuration(ms: number | null): string {
  if (ms == null) return "—";
  const secs = Math.round(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  const rem = secs % 60;
  return `${mins}m ${rem}s`;
}
