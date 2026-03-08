import { Link } from "react-router-dom";
import SessionTable from "../components/SessionTable";
import { useApi } from "../hooks/useApi";
import type { Project, SessionList } from "../api/types";

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
