import { Link } from "react-router-dom";
import type { Session } from "../api/types";

export default function SessionTable({ sessions }: { sessions: Session[] }) {
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

export function statusColor(status: string): string {
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

export function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function formatDuration(ms: number | null): string {
  if (ms == null) return "—";
  const secs = Math.round(ms / 1000);
  if (secs < 60) return `${secs}s`;
  const mins = Math.floor(secs / 60);
  const rem = secs % 60;
  return `${mins}m ${rem}s`;
}
