import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useSession } from "@/hooks/queries/use-sessions";
import { useStopSession } from "@/hooks/mutations/use-sessions";
import AgentTreeFlow from "@/components/AgentTreeFlow";
import AgentLogViewer from "@/components/AgentLogViewer";
import ChatPanel from "@/components/ChatPanel";
import { formatTime, formatDuration } from "@/components/SessionTable";
import { useSessionWS } from "@/hooks/useSessionWS";
import SessionDetailSkeleton from "@/components/skeletons/SessionDetailSkeleton";
import MarkdownContent from "@/components/MarkdownContent";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { ScrollArea } from "@/components/ui/scroll-area";
import ViewToggle from "@/components/ViewToggle";
import { cn, formatTokens, formatCost } from "@/lib/utils";
import {
  AlertCircle,
  ArrowLeft,
  ChevronRight,
  OctagonX,
} from "lucide-react";
import type { SessionDetail as SessionDetailType, TraceEvent } from "@/api/types";

export default function SessionDetail() {
  const { projectId, runId } = useParams();
  const [searchParams] = useSearchParams();
  const pid = Number(projectId);

  const isActive = (status?: string) =>
    status === "starting" || status === "running";

  const session = useSession(pid, runId ?? "", {
    refetchInterval: undefined,
  });

  // Auto-poll session metadata while active
  const sessionData = session.data;
  const active = isActive(sessionData?.status);
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => session.refetch(), 2000);
    return () => clearInterval(id);
  }, [active, session]);

  const isInteractive = !!sessionData?.interactive;
  const { pendingAskUsers, chatMessages, traceEvents, treeData: wsTreeData, connected, agentLogs, respond, subscribeLogs, unsubscribeLogs } = useSessionWS(
    runId ?? "",
    true,  // always connect — terminal sessions get snapshots then close
  );
  const treeData = wsTreeData ?? sessionData?.tree ?? null;
  const restEvents = sessionData?.events ?? [];
  const displayEvents = traceEvents.length > 0 ? traceEvents : restEvents;

  // Auto-switch to Chat tab when a question arrives
  const [activeTab, setActiveTab] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (pendingAskUsers.length > 0) setActiveTab("chat");
  }, [pendingAskUsers]);

  if (session.isLoading) {
    return <SessionDetailSkeleton />;
  }
  if (session.error) {
    return (
      <div className="flex items-center gap-2 text-destructive">
        <AlertCircle className="h-4 w-4" />
        <span>Error: {session.error.message}</span>
      </div>
    );
  }
  if (!sessionData) {
    return (
      <div className="flex items-center gap-2 text-destructive">
        <AlertCircle className="h-4 w-4" />
        <span>Session not found</span>
      </div>
    );
  }

  const artifacts = extractArtifacts(displayEvents);
  const outputRef = extractOutputRef(displayEvents);
  const defaultTab =
    searchParams.get("tab") ?? (!active ? "overview" : "agent-tree");

  return (
    <div className="space-y-6">
      <SessionHeader
        session={sessionData}
        projectId={pid}
        runId={runId ?? ""}
        onStopped={() => session.refetch()}
      />

      <SessionMetadata session={sessionData} />

      <Tabs
        value={activeTab ?? defaultTab}
        onValueChange={setActiveTab}
      >
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          {isInteractive && (
            <TabsTrigger value="chat" className="relative">
              Chat
              {pendingAskUsers.length > 0 && (
                <span className="ml-1.5 inline-block h-2 w-2 animate-pulse rounded-full bg-amber-500" />
              )}
            </TabsTrigger>
          )}
          <TabsTrigger value="agent-tree">Agent Tree</TabsTrigger>
          <TabsTrigger value="logs">Logs</TabsTrigger>
          <TabsTrigger value="trace">
            Trace{displayEvents.length > 0 && ` (${displayEvents.length})`}
          </TabsTrigger>
          <TabsTrigger value="artifacts">
            Artifacts{artifacts.length > 0 && ` (${artifacts.length})`}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="space-y-4">
          {sessionData.user_task && (
            <OverviewSection label="User Task" defaultOpen>
              <ContentView content={sessionData.user_task} />
            </OverviewSection>
          )}

          {sessionData.task && (
            <OverviewSection label="Task" defaultOpen={!sessionData.user_task}>
              <ContentView content={sessionData.task} />
            </OverviewSection>
          )}

          {outputRef && (
            <OverviewSection label="Output" defaultOpen>
              <ArtifactContentView
                runId={sessionData.run_id}
                hash={outputRef}
              />
            </OverviewSection>
          )}

          {sessionData.cost && sessionData.cost.by_role.length > 0 && (
            <OverviewSection label="Cost Breakdown" defaultOpen={false}>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Role</TableHead>
                    <TableHead className="text-right">Input</TableHead>
                    <TableHead className="text-right">Output</TableHead>
                    <TableHead className="text-right">Cost</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sessionData.cost.by_role.map((rc) => (
                    <TableRow key={rc.role}>
                      <TableCell className="font-medium">{rc.role}</TableCell>
                      <TableCell className="text-right">{formatTokens(rc.input_tokens)}</TableCell>
                      <TableCell className="text-right">{formatTokens(rc.output_tokens)}</TableCell>
                      <TableCell className="text-right">{formatCost(rc.cost_usd) ?? "-"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </OverviewSection>
          )}

          {!sessionData.user_task && !sessionData.task && !outputRef && (
            <p className="text-sm text-muted-foreground">
              No overview information available yet.
            </p>
          )}
        </TabsContent>

        {isInteractive && (
          <TabsContent value="chat">
            <ChatPanel
              pendingAskUsers={pendingAskUsers}
              initialMessages={chatMessages}
              respond={respond}
            />
          </TabsContent>
        )}

        <TabsContent value="agent-tree">
          <AgentTreeFlow treeData={treeData} connected={connected} />
        </TabsContent>

        <TabsContent value="logs">
          {Object.keys(sessionData.agents).length > 0 ? (
            <AgentLogViewer
              runId={sessionData.run_id}
              agents={sessionData.agents}
              active={active}
              agentLogs={agentLogs}
              wsConnected={connected}
              subscribeLogs={subscribeLogs}
              unsubscribeLogs={unsubscribeLogs}
            />
          ) : (
            <p className="text-sm text-muted-foreground">
              No agents registered yet.
            </p>
          )}
        </TabsContent>

        <TabsContent value="trace">
          {displayEvents.length > 0 ? (
            <EventTimeline
              events={displayEvents}
              runId={sessionData.run_id}
            />
          ) : (
            <p className="text-sm text-muted-foreground">
              No trace events recorded yet.
            </p>
          )}
        </TabsContent>

        <TabsContent value="artifacts">
          {artifacts.length > 0 ? (
            <ArtifactList
              artifacts={artifacts}
              runId={sessionData.run_id}
            />
          ) : (
            <p className="text-sm text-muted-foreground">
              No artifacts recorded yet.
            </p>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Session header with stop button
// ---------------------------------------------------------------------------

function SessionHeader({
  session,
  projectId,
  runId,
  onStopped,
}: {
  session: SessionDetailType;
  projectId: number;
  runId: string;
  onStopped: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const stopSession = useStopSession();
  const active =
    session.status === "starting" || session.status === "running";

  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-3">
        <Button variant="outline" size="sm" asChild>
          <Link to={projectId === 0 ? "/imu" : `/projects/${projectId}`}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back
          </Link>
        </Button>
        <h1 className="text-2xl font-bold tracking-tight">
          Session {session.run_id.slice(0, 16)}
        </h1>
      </div>
      <div className="flex gap-2">
        {active &&
          (confirming ? (
            <div className="flex gap-1">
              <Button
                size="sm"
                variant="destructive"
                onClick={async () => {
                  await stopSession.mutateAsync(runId);
                  setConfirming(false);
                  onStopped();
                }}
                disabled={stopSession.isPending}
              >
                Confirm
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => setConfirming(false)}
              >
                Cancel
              </Button>
            </div>
          ) : (
            <Button variant="destructive" onClick={() => setConfirming(true)}>
              <OctagonX className="mr-2 h-4 w-4" />
              Stop Session
            </Button>
          ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Session metadata card
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: string }) {
  const variant = statusVariant(status);
  return (
    <Badge
      variant="outline"
      className={cn(
        "text-xs font-medium",
        variant === "running" && "border-green-200 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950 dark:text-green-400",
        variant === "success" && "border-green-200 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950 dark:text-green-400",
        variant === "error" && "border-red-200 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-400",
        variant === "warning" &&
          "border-orange-200 bg-orange-50 text-orange-700 dark:border-orange-800 dark:bg-orange-950 dark:text-orange-400",
        variant === "default" && "border-muted bg-muted text-muted-foreground",
      )}
    >
      {status === "running" && (
        <span className="mr-1.5 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-green-500" />
      )}
      {status}
    </Badge>
  );
}

function statusVariant(status: string): string {
  switch (status) {
    case "running":
    case "starting":
      return "running";
    case "completed":
      return "success";
    case "failed":
      return "error";
    case "stopped":
      return "warning";
    default:
      return "default";
  }
}

function SessionMetadata({ session }: { session: SessionDetailType }) {
  return (
    <Card>
      <CardContent className="pt-6">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
          <dt className="font-medium text-muted-foreground">Status</dt>
          <dd>
            <StatusBadge status={session.status} />
          </dd>
          <dt className="font-medium text-muted-foreground">Role</dt>
          <dd>{session.role}</dd>
          <dt className="font-medium text-muted-foreground">Runtime</dt>
          <dd>{session.runtime}</dd>
          <dt className="font-medium text-muted-foreground">Isolation</dt>
          <dd>{session.isolation}</dd>
          <dt className="font-medium text-muted-foreground">Started</dt>
          <dd>{formatTime(session.started_at)}</dd>
          {session.ended_at && (
            <>
              <dt className="font-medium text-muted-foreground">Ended</dt>
              <dd>{formatTime(session.ended_at)}</dd>
            </>
          )}
          <dt className="font-medium text-muted-foreground">Duration</dt>
          <dd>{formatDuration(session.duration_ms)}</dd>
          {session.exit_code !== null && (
            <>
              <dt className="font-medium text-muted-foreground">Exit Code</dt>
              <dd>{session.exit_code}</dd>
            </>
          )}
          {session.cost && (
            <>
              {session.cost.total_cost_usd != null && (
                <>
                  <dt className="font-medium text-muted-foreground">Cost</dt>
                  <dd>{formatCost(session.cost.total_cost_usd)}</dd>
                </>
              )}
              <dt className="font-medium text-muted-foreground">Tokens</dt>
              <dd>
                {formatTokens(session.cost.total_input_tokens)} in / {formatTokens(session.cost.total_output_tokens)} out
                {session.cost.total_cache_read_tokens > 0 && (
                  <span className="text-muted-foreground"> ({formatTokens(session.cost.total_cache_read_tokens)} cached)</span>
                )}
              </dd>
            </>
          )}
        </dl>
      </CardContent>
    </Card>
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

// ---------------------------------------------------------------------------
// Overview helpers: section wrapper + markdown/raw toggle
// ---------------------------------------------------------------------------

function OverviewSection({
  label,
  defaultOpen,
  children,
}: {
  label: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Collapsible defaultOpen={defaultOpen}>
      <div className="space-y-2">
        <CollapsibleTrigger className="flex items-center gap-1 text-sm font-medium text-muted-foreground hover:text-foreground">
          <ChevronRight className="h-3.5 w-3.5 transition-transform [[data-state=open]>&]:rotate-90" />
          {label}
        </CollapsibleTrigger>
        <CollapsibleContent>
          <Card>
            <CardContent className="pt-4">{children}</CardContent>
          </Card>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
}


function ContentView({ content }: { content: string }) {
  const [view, setView] = useState<"markdown" | "raw">("markdown");
  return (
    <>
      <ViewToggle view={view} onChange={setView} />
      {view === "markdown" ? (
        <MarkdownContent content={content} className="text-sm" />
      ) : (
        <pre className="whitespace-pre-wrap break-words rounded-md bg-muted/30 p-3 font-mono text-xs leading-relaxed">
          {content}
        </pre>
      )}
    </>
  );
}

function ArtifactContentView({ runId, hash }: { runId: string; hash: string }) {
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"markdown" | "raw">("markdown");

  useEffect(() => {
    fetch(`/api/sessions/${runId}/artifacts/${hash}`)
      .then((res) => {
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        return res.text();
      })
      .then(setContent)
      .catch((err) => setError(err.message));
  }, [runId, hash]);

  if (error) return <span className="text-destructive">Error: {error}</span>;
  if (content === null)
    return <span className="text-muted-foreground">Loading...</span>;
  return (
    <>
      <ViewToggle view={view} onChange={setView} />
      {view === "markdown" ? (
        <MarkdownContent content={content} className="text-sm" />
      ) : (
        <pre className="whitespace-pre-wrap break-words rounded-md bg-muted/30 p-3 font-mono text-xs leading-relaxed">
          {content}
        </pre>
      )}
    </>
  );
}


function extractOutputRef(events: TraceEvent[]): string | null {
  for (const e of events) {
    if (e.event === "session_end" && e.data.output_ref) {
      return String(e.data.output_ref);
    }
  }
  return null;
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
    if (e.event === "memory_get") {
      if (d.cards_ref) {
        artifacts.push({
          label: `Memory Cards (${d.provider || "memory"})`,
          hash: String(d.cards_ref),
          event: e.event,
        });
      }
      if (d.behavior_ref) {
        artifacts.push({
          label: `Memory Get Behavior (${d.role || "agent"})`,
          hash: String(d.behavior_ref),
          event: e.event,
        });
      }
      if (d.task_ref) {
        artifacts.push({
          label: `Memory Get Task (${d.role || "agent"})`,
          hash: String(d.task_ref),
          event: e.event,
        });
      }
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
    if (e.event === "memory_remember" && d.content_ref) {
      artifacts.push({
        label: `Memory Remember (${d.provider || "memory"})`,
        hash: String(d.content_ref),
        event: e.event,
      });
    }
    if (e.event === "memory_recall" && d.results_ref) {
      artifacts.push({
        label: `Memory Recall (${d.provider || "memory"})`,
        hash: String(d.results_ref),
        event: e.event,
      });
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
  return (
    <div className="space-y-1">
      {artifacts.map((a) => (
        <Collapsible key={`${a.event}-${a.hash}`}>
          <CollapsibleTrigger className="flex w-full items-center gap-2 rounded-md bg-muted/50 px-3 py-2 text-sm hover:bg-muted">
            <ChevronRight className="h-3 w-3 transition-transform [[data-state=open]>&]:rotate-90" />
            <span className="font-medium text-primary">{a.label}</span>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <ArtifactContent runId={runId} hash={a.hash} />
          </CollapsibleContent>
        </Collapsible>
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

  if (error) {
    return (
      <p className="px-3 py-2 text-sm text-destructive">Error: {error}</p>
    );
  }
  if (content === null) {
    return (
      <p className="px-3 py-2 text-sm text-muted-foreground">Loading...</p>
    );
  }
  return (
    <ScrollArea className="max-h-[300px] overflow-hidden">
      <pre className="whitespace-pre-wrap break-words rounded-b-md bg-muted/30 px-3 py-2 font-mono text-xs leading-relaxed">
        {content}
      </pre>
    </ScrollArea>
  );
}

// ---------------------------------------------------------------------------
// Event timeline
// ---------------------------------------------------------------------------

function EventBadge({ event }: { event: string }) {
  const variant = eventVariant(event);
  return (
    <Badge
      variant="outline"
      className={cn(
        "text-xs font-medium",
        variant === "running" && "border-green-200 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950 dark:text-green-400",
        variant === "success" && "border-green-200 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950 dark:text-green-400",
        variant === "error" && "border-red-200 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-400",
        variant === "default" && "border-muted bg-muted text-muted-foreground",
      )}
    >
      {event}
    </Badge>
  );
}

function eventVariant(event: string): string {
  if (event.endsWith("_start") || event === "agent_spawn") return "running";
  if (event.endsWith("_end")) return "success";
  if (event.includes("denied") || event.includes("error")) return "error";
  return "default";
}

function EventTimeline({
  events,
  runId,
}: {
  events: TraceEvent[];
  runId: string;
}) {
  const [artifact, setArtifact] = useState<{
    hash: string;
    label: string;
  } | null>(null);

  return (
    <>
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Event</TableHead>
                <TableHead>Span</TableHead>
                <TableHead>Details</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {events.map((e, i) => (
                <TableRow key={i}>
                  <TableCell className="text-sm text-muted-foreground">
                    {formatTime(e.ts)}
                  </TableCell>
                  <TableCell>
                    <EventBadge event={e.event} />
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {e.span_id.slice(0, 8)}
                  </TableCell>
                  <TableCell className="max-w-[400px] text-sm">
                    {formatEventData(e, (hash, label) =>
                      setArtifact({ hash, label }),
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={!!artifact} onOpenChange={() => setArtifact(null)}>
        <DialogContent className="max-w-3xl overflow-hidden">
          <DialogHeader>
            <DialogTitle>{artifact?.label}</DialogTitle>
          </DialogHeader>
          {artifact && (
            <ArtifactModalContent runId={runId} hash={artifact.hash} />
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

function ArtifactModalContent({
  runId,
  hash,
}: {
  runId: string;
  hash: string;
}) {
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"markdown" | "raw">("markdown");
  const containerRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  // Scope Cmd+A / Ctrl+A to content area only (excludes tab buttons)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const el = contentRef.current ?? containerRef.current;
      if (!el) return;
      if ((e.metaKey || e.ctrlKey) && e.key === "a") {
        e.preventDefault();
        const sel = window.getSelection();
        if (sel) {
          sel.removeAllRanges();
          const range = document.createRange();
          range.selectNodeContents(el);
          sel.addRange(range);
        }
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  useEffect(() => {
    fetch(`/api/sessions/${runId}/artifacts/${hash}`)
      .then((res) => {
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        return res.text();
      })
      .then(setContent)
      .catch((err) => setError(err.message));
  }, [runId, hash]);

  return (
    <div ref={containerRef} className="space-y-2">
      {error ? (
        <p className="text-sm text-destructive">Error: {error}</p>
      ) : content === null ? (
        <p className="text-sm text-muted-foreground">Loading...</p>
      ) : (
        <>
          <ViewToggle view={view} onChange={setView} />
          <div ref={contentRef} className="max-h-[60vh] overflow-y-auto">
            {view === "markdown" ? (
              <div className="p-4">
                <MarkdownContent content={content} className="text-sm" />
              </div>
            ) : (
              <pre className="whitespace-pre-wrap break-words rounded-md bg-muted/30 p-4 font-mono text-xs leading-relaxed">
                {content}
              </pre>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function formatEventData(
  e: TraceEvent,
  onArtifactClick: (hash: string, label: string) => void,
): React.ReactNode {
  const d = e.data;

  const buttons: React.ReactNode[] = [];
  for (const [key, value] of Object.entries(d)) {
    if (key.endsWith("_ref") && value) {
      const label = key.replace(/_ref$/, "");
      buttons.push(
        <button
          key={key}
          className="rounded border border-primary/30 bg-primary/5 px-1.5 py-0.5 font-mono text-xs text-primary hover:bg-primary/10"
          onClick={() => onArtifactClick(String(value), label)}
        >
          {label}
        </button>,
      );
    }
  }

  const params: React.ReactNode[] = [];
  for (const [key, value] of Object.entries(d)) {
    if (key.endsWith("_ref")) continue;
    if (value === null || value === undefined || value === "") continue;
    const display =
      key === "duration_ms"
        ? formatDuration(value as number)
        : Array.isArray(value)
          ? value.join(", ")
          : String(value);
    params.push(
      <span key={key}>
        <span className="text-muted-foreground">{key}=</span>
        <span>{display}</span>
      </span>,
    );
  }

  return (
    <>
      {buttons.length > 0 && (
        <div className="mb-1 flex flex-wrap gap-1">{buttons}</div>
      )}
      {params.length > 0 && (
        <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
          {params}
        </div>
      )}
    </>
  );
}
