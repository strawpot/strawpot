import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import AgentTreeFlow from "../components/AgentTreeFlow";
import { statusColor, formatTime, formatDuration } from "../components/SessionTable";
import { useApi } from "../hooks/useApi";
import { useTraceSSE } from "../hooks/useTraceSSE";
import type { SessionDetail as SessionDetailType, TraceEvent } from "../api/types";

export default function SessionDetail() {
  const { projectId, runId } = useParams();
  const { data: session, loading, error, refetch } = useApi<SessionDetailType>(
    `/projects/${projectId}/sessions/${runId}`,
  );
  const [confirming, setConfirming] = useState(false);

  // Auto-poll session metadata while active
  const isActive = session?.status === "starting" || session?.status === "running";
  useEffect(() => {
    if (!isActive) return;
    const id = setInterval(refetch, 5000);
    return () => clearInterval(id);
  }, [isActive, refetch]);

  // SSE for live trace events on active sessions
  const { events: sseEvents } = useTraceSSE(runId ?? "", isActive);
  const displayEvents = useMemo<TraceEvent[]>(() => {
    if (isActive && sseEvents.length > 0) return sseEvents;
    return session?.events ?? [];
  }, [isActive, sseEvents, session?.events]);

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

      <section className="dashboard-section">
        <h2>Agent Tree</h2>
        <AgentTreeFlow runId={session.run_id} />
      </section>

      {displayEvents.length > 0 && (
        <section className="dashboard-section">
          <h2>Trace Events ({displayEvents.length})</h2>
          <EventTimeline events={displayEvents} runId={session.run_id} />
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

function EventTimeline({ events, runId }: { events: TraceEvent[]; runId: string }) {
  const [artifact, setArtifact] = useState<{ hash: string; label: string } | null>(null);

  return (
    <>
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
              <td className="cell-task">
                {formatEventData(e, (hash, label) => setArtifact({ hash, label }))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {artifact && (
        <ArtifactModal
          runId={runId}
          artifactHash={artifact.hash}
          label={artifact.label}
          onClose={() => setArtifact(null)}
        />
      )}
    </>
  );
}

function ArtifactModal({
  runId,
  artifactHash,
  label,
  onClose,
}: {
  runId: string;
  artifactHash: string;
  label: string;
  onClose: () => void;
}) {
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/sessions/${runId}/artifacts/${artifactHash}`)
      .then((res) => {
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        return res.text();
      })
      .then(setContent)
      .catch((err) => setError(err.message));
  }, [runId, artifactHash]);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal modal-lg" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{label}</h3>
          <button className="btn btn-sm" onClick={onClose}>Close</button>
        </div>
        <div className="modal-body">
          {error ? (
            <p className="error">Error: {error}</p>
          ) : content === null ? (
            <p>Loading...</p>
          ) : (
            <pre className="artifact-content">{content}</pre>
          )}
        </div>
      </div>
    </div>
  );
}

function eventColor(event: string): string {
  if (event.endsWith("_start") || event === "agent_spawn") return "running";
  if (event.endsWith("_end")) return "success";
  if (event.includes("denied") || event.includes("error")) return "error";
  return "default";
}

function formatEventData(
  e: TraceEvent,
  onArtifactClick: (hash: string, label: string) => void,
): React.ReactNode {
  const parts: React.ReactNode[] = [];
  const d = e.data;

  if (d.role) parts.push(`role=${d.role}`);
  if (d.provider) parts.push(`provider=${d.provider}`);
  if (d.runtime) parts.push(`runtime=${d.runtime}`);
  if (d.exit_code !== undefined) parts.push(`exit=${d.exit_code}`);
  if (d.duration_ms !== undefined) parts.push(formatDuration(d.duration_ms as number));
  if (d.reason) parts.push(String(d.reason));
  if (d.card_count !== undefined) parts.push(`${d.card_count} cards`);
  if (d.entry_count !== undefined) parts.push(`${d.entry_count} entries`);

  // Delegation summary — styled for emphasis
  if (d.summary) {
    parts.push(
      <span key="summary" className="delegate-summary">
        {String(d.summary).slice(0, 120)}
      </span>,
    );
  }

  // Clickable artifact refs
  for (const [key, value] of Object.entries(d)) {
    if (key.endsWith("_ref") && value) {
      const label = key.replace(/_ref$/, "");
      parts.push(
        <button
          key={key}
          className="btn-artifact"
          onClick={() => onArtifactClick(String(value), label)}
        >
          {label}
        </button>,
      );
    }
  }

  if (parts.length === 0 && Object.keys(d).length > 0) {
    return Object.entries(d)
      .filter(([k]) => !k.endsWith("_ref"))
      .map(([k, v]) => `${k}=${v}`)
      .join(", ");
  }

  return parts.map((p, i) => (
    <span key={i}>
      {i > 0 && typeof p === "string" && ", "}
      {i > 0 && typeof p !== "string" && " "}
      {p}
    </span>
  ));
}
