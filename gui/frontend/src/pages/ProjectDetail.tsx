import { Link, useParams } from "react-router-dom";
import SessionTable from "../components/SessionTable";
import { useApi } from "../hooks/useApi";
import type { Project, Session } from "../api/types";

export default function ProjectDetail() {
  const { projectId } = useParams();
  const { data: project, loading: pLoading, error: pError } =
    useApi<Project>(`/projects/${projectId}`);
  const { data: sessions, loading: sLoading, error: sError } =
    useApi<Session[]>(`/projects/${projectId}/sessions`);

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
        <Link to="/projects" className="btn">
          Back to Projects
        </Link>
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
