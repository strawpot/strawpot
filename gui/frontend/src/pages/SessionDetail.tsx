import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { statusColor, formatTime, formatDuration } from "../components/SessionTable";
import { useApi } from "../hooks/useApi";
import type { AgentInfo, SessionDetail as SessionDetailType, TraceEvent } from "../api/types";

export default function SessionDetail() {
  const { projectId, runId } = useParams();
  const { data: session, loading, error, refetch } = useApi<SessionDetailType>(
    `/projects/${projectId}/sessions/${runId}`,
  );
  const [confirming, setConfirming] = useState(false);

  if (loading) return <p>Loading...</p>;
  if (error) return <p className="error">Error: {error}</p>;
  if (!session) return <p className="error">Session not found</p>;

  return (
    <div>
      <div className="page-header">
        <h1>Session {session.run_id.slice(0, 16)}</h1>
        <div className="page-header-actions">
          {(session.status === "starting" || session.status === "running") &&
            (confirming ? (
              <span className="confirm-group">
                <button
                  className="btn btn-danger btn-sm"
                  onClick={async () => {
                    await api.post(`/sessions/${runId}/stop`);
                    setConfirming(false);
                    refetch();
                  }}
                >
                  Confirm
                </button>
                <button
                  className="btn btn-sm"
                  onClick={() => setConfirming(false)}
                >
                  Cancel
                </button>
              </span>
            ) : (
              <button
                className="btn btn-danger"
                onClick={() => setConfirming(true)}
              >
                Stop Session
              </button>
            ))}
          <Link to={`/projects/${projectId}`} className="btn">
            Back to Project
          </Link>
        </div>
      </div>

      <div className="detail-grid">
        <DetailRow label="Status">
          <span className={`badge badge-${statusColor(session.status)}`}>
            {session.status}
          </span>
        </DetailRow>
        <DetailRow label="Role">{session.role}</DetailRow>
        <DetailRow label="Runtime">{session.runtime}</DetailRow>
        <DetailRow label="Isolation">{session.isolation}</DetailRow>
        <DetailRow label="Started">{formatTime(session.started_at)}</DetailRow>
        {session.ended_at && (
          <DetailRow label="Ended">{formatTime(session.ended_at)}</DetailRow>
        )}
        <DetailRow label="Duration">{formatDuration(session.duration_ms)}</DetailRow>
        {session.exit_code !== null && (
          <DetailRow label="Exit Code">{session.exit_code}</DetailRow>
        )}
      </div>

      {session.task && (
        <section className="dashboard-section">
          <h2>Task</h2>
          <div className="detail-block">{session.task}</div>
        </section>
      )}

      {session.summary && (
        <section className="dashboard-section">
          <h2>Summary</h2>
          <div className="detail-block">{session.summary}</div>
        </section>
      )}

      {Object.keys(session.agents).length > 0 && (
        <section className="dashboard-section">
          <h2>Agents ({Object.keys(session.agents).length})</h2>
          <AgentTree agents={session.agents} />
        </section>
      )}

      {session.events.length > 0 && (
        <section className="dashboard-section">
          <h2>Trace Events ({session.events.length})</h2>
          <EventTimeline events={session.events} />
        </section>
      )}
    </div>
  );
}

function DetailRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="project-info-row">
      <span className="project-info-label">{label}</span>
      <span className="project-info-value">{children}</span>
    </div>
  );
}

function AgentTree({ agents }: { agents: Record<string, AgentInfo> }) {
  // Find root agents (no parent), then render children recursively
  const entries = Object.entries(agents);
  const roots = entries.filter(([, a]) => !a.parent);

  const renderAgent = (id: string, agent: AgentInfo, depth: number) => {
    const children = entries.filter(([, a]) => a.parent === id);
    return (
      <div key={id} className="agent-node" style={{ marginLeft: depth * 20 }}>
        <div className="agent-header">
          <span className="agent-role">{agent.role}</span>
          <span className="agent-meta">{agent.runtime}</span>
          {agent.pid && <span className="agent-meta">PID {agent.pid}</span>}
        </div>
        {children.map(([cId, cAgent]) => renderAgent(cId, cAgent, depth + 1))}
      </div>
    );
  };

  return (
    <div className="agent-tree">
      {roots.map(([id, agent]) => renderAgent(id, agent, 0))}
    </div>
  );
}

function EventTimeline({ events }: { events: TraceEvent[] }) {
  return (
    <table className="session-table">
      <thead>
        <tr>
          <th>Time</th>
          <th>Event</th>
          <th>Span</th>
          <th>Details</th>
        </tr>
      </thead>
      <tbody>
        {events.map((e, i) => (
          <tr key={i}>
            <td>{formatTime(e.ts)}</td>
            <td>
              <span className={`badge badge-${eventColor(e.event)}`}>
                {e.event}
              </span>
            </td>
            <td className="agent-meta">{e.span_id.slice(0, 8)}</td>
            <td className="cell-task">{formatEventData(e)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function eventColor(event: string): string {
  if (event.endsWith("_start") || event === "agent_spawn") return "running";
  if (event.endsWith("_end")) return "success";
  if (event.includes("denied") || event.includes("error")) return "error";
  return "default";
}

function formatEventData(e: TraceEvent): string {
  const parts: string[] = [];
  const d = e.data;
  if (d.role) parts.push(`role=${d.role}`);
  if (d.runtime) parts.push(`runtime=${d.runtime}`);
  if (d.exit_code !== undefined) parts.push(`exit=${d.exit_code}`);
  if (d.duration_ms !== undefined) parts.push(`${formatDuration(d.duration_ms as number)}`);
  if (d.summary) parts.push(String(d.summary).slice(0, 80));
  if (d.reason) parts.push(String(d.reason));
  if (d.card_count !== undefined) parts.push(`${d.card_count} cards`);
  if (d.entry_count !== undefined) parts.push(`${d.entry_count} entries`);
  if (parts.length === 0 && Object.keys(d).length > 0) {
    return Object.entries(d)
      .filter(([k]) => !k.endsWith("_ref"))
      .map(([k, v]) => `${k}=${v}`)
      .join(", ");
  }
  return parts.join(", ");
}
