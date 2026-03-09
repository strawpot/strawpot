import { useEffect, useState } from "react";
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
    const id = setInterval(refetch, 2000);
    return () => clearInterval(id);
  }, [isActive, refetch]);

  // SSE for live trace events on active sessions
  const { events: sseEvents } = useTraceSSE(runId ?? "", isActive);
  const restEvents = session?.events ?? [];
  // SSE sends full snapshots — prefer SSE when it has data, else REST
  const displayEvents = sseEvents.length > 0 ? sseEvents : restEvents;

  if (loading) return <p>Loading...</p>;
  if (error) return <p className="error">Error: {error}</p>;
  if (!session) return <p className="error">Session not found</p>;

  // Extract key artifacts from trace events
  const artifacts = extractArtifacts(displayEvents);

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

      {displayEvents.length > 0 && (
        <section className="dashboard-section">
          <h2>Trace Events ({displayEvents.length})</h2>
          <EventTimeline events={displayEvents} runId={session.run_id} />
        </section>
      )}

      {session.summary && (
        <section className="dashboard-section">
          <h2>Summary</h2>
          <div className="detail-block">{session.summary}</div>
        </section>
      )}

      {artifacts.length > 0 && (
        <section className="dashboard-section">
          <h2>Artifacts</h2>
          <ArtifactList artifacts={artifacts} runId={session.run_id} />
        </section>
      )}

      <section className="dashboard-section">
        <h2>Agent Tree</h2>
        <AgentTreeFlow runId={session.run_id} />
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Artifact extraction from trace events
// ---------------------------------------------------------------------------

interface ArtifactEntry {
  label: string;
  hash: string;
  event: string;
  agentId?: string;
}

function extractArtifacts(events: TraceEvent[]): ArtifactEntry[] {
  const artifacts: ArtifactEntry[] = [];
  for (const e of events) {
    const d = e.data;
    if (e.event === "agent_spawn") {
      if (d.context_ref) {
        artifacts.push({
          label: `Agent Context (${d.role || "agent"})`,
          hash: String(d.context_ref),
          event: e.event,
          agentId: d.agent_id ? String(d.agent_id) : undefined,
        });
      }
      if (d.task_ref) {
        artifacts.push({
          label: `Agent Task (${d.role || "agent"})`,
          hash: String(d.task_ref),
          event: e.event,
          agentId: d.agent_id ? String(d.agent_id) : undefined,
        });
      }
    }
    if (e.event === "session_end" && d.output_ref) {
      artifacts.push({
        label: "Session Output",
        hash: String(d.output_ref),
        event: e.event,
      });
    }
    if (e.event === "agent_end" && d.output_ref) {
      artifacts.push({
        label: `Agent Output (${d.agent_id || "agent"})`,
        hash: String(d.output_ref),
        event: e.event,
        agentId: d.agent_id ? String(d.agent_id) : undefined,
      });
    }
    if (e.event === "memory_get" && d.cards_ref) {
      artifacts.push({
        label: `Memory Cards (${d.provider || "memory"})`,
        hash: String(d.cards_ref),
        event: e.event,
      });
    }
    if (e.event === "memory_dump") {
      if (d.output_ref) {
        artifacts.push({
          label: `Memory Dump Output (${d.provider || "memory"})`,
          hash: String(d.output_ref),
          event: e.event,
        });
      }
      if (d.behavior_ref) {
        artifacts.push({
          label: `Memory Dump Behavior (${d.provider || "memory"})`,
          hash: String(d.behavior_ref),
          event: e.event,
        });
      }
      if (d.task_ref) {
        artifacts.push({
          label: `Memory Dump Task (${d.provider || "memory"})`,
          hash: String(d.task_ref),
          event: e.event,
        });
      }
    }
    if (e.event === "delegate_start" && d.context_ref) {
      artifacts.push({
        label: `Delegation Context (${d.role || "delegate"})`,
        hash: String(d.context_ref),
        event: e.event,
      });
    }
    if (e.event === "delegate_end" && d.output_ref) {
      artifacts.push({
        label: `Delegation Output (${d.role || "delegate"})`,
        hash: String(d.output_ref),
        event: e.event,
      });
    }
  }
  return artifacts;
}

// ---------------------------------------------------------------------------
// Artifact list with expandable content
// ---------------------------------------------------------------------------

function ArtifactList({
  artifacts,
  runId,
}: {
  artifacts: ArtifactEntry[];
  runId: string;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <div className="artifact-list">
      {artifacts.map((a) => (
        <div key={`${a.event}-${a.hash}`} className="artifact-item">
          <button
            className="artifact-toggle"
            onClick={() =>
              setExpanded(expanded === a.hash ? null : a.hash)
            }
          >
            <span className="artifact-icon">{expanded === a.hash ? "▼" : "▶"}</span>
            <span className="artifact-label">{a.label}</span>
          </button>
          {expanded === a.hash && (
            <ArtifactContent runId={runId} hash={a.hash} />
          )}
        </div>
      ))}
    </div>
  );
}

function ArtifactContent({ runId, hash }: { runId: string; hash: string }) {
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/api/sessions/${runId}/artifacts/${hash}`)
      .then((res) => {
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        return res.text();
      })
      .then(setContent)
      .catch((err) => setError(err.message));
  }, [runId, hash]);

  if (error) return <p className="error">Error: {error}</p>;
  if (content === null) return <p className="loading-text">Loading...</p>;
  return <pre className="artifact-content">{content}</pre>;
}

// ---------------------------------------------------------------------------
// Detail row
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Event timeline
// ---------------------------------------------------------------------------

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
  const d = e.data;

  // Collect artifact buttons
  const buttons: React.ReactNode[] = [];
  for (const [key, value] of Object.entries(d)) {
    if (key.endsWith("_ref") && value) {
      const label = key.replace(/_ref$/, "");
      buttons.push(
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

  // Collect all non-ref data fields as key=value params
  const params: React.ReactNode[] = [];
  for (const [key, value] of Object.entries(d)) {
    if (key.endsWith("_ref")) continue;
    if (value === null || value === undefined || value === "") continue;
    const display = key === "duration_ms"
      ? formatDuration(value as number)
      : Array.isArray(value)
        ? value.join(", ")
        : String(value);
    params.push(
      <span key={key}>
        <span className="event-param-key">{key}=</span>
        <span className="event-param-value">{display}</span>
      </span>,
    );
  }

  // Delegation summary — styled for emphasis
  const summary = d.summary ? (
    <span key="summary" className="delegate-summary">
      {String(d.summary)}
    </span>
  ) : null;

  return (
    <>
      {buttons.length > 0 && (
        <div className="event-artifacts">{buttons}</div>
      )}
      {summary}
      {params.length > 0 && (
        <div className="event-params">{params}</div>
      )}
    </>
  );
}
