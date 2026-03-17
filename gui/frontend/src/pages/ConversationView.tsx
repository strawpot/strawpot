import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useConversationInfinite } from "@/hooks/queries/use-conversations";
import { useSubmitConversationTask, useRenameConversation, useCancelPendingTask, useCancelQueuedTask } from "@/hooks/mutations/use-conversations";
import { useStopSession } from "@/hooks/mutations/use-sessions";
import { useSessionWS } from "@/hooks/useSessionWS";
import { useProjectResources } from "@/hooks/queries/use-project-resources";
import { useProjectFiles, useProjectConfig } from "@/hooks/queries/use-projects";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/query-keys";
import { AlertCircle, ArrowUpRight, BotMessageSquare, CheckCircle2, CornerDownLeft, ExternalLink, Loader2, MessageSquare, Paperclip, Settings, Square, Upload, X, XCircle } from "lucide-react";
import type { AskUserPending, ChatMessage, ConversationSession, ProjectFile } from "@/api/types";
import MarkdownContent from "@/components/MarkdownContent";
import { SourceBadge } from "@/components/SourceBadge";

function formatDuration(ms: number | null): string {
  if (ms === null) return "";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return rem > 0 ? `${m}m ${rem}s` : `${m}m`;
}

function StatusBadge({ status }: { status: string }) {
  if (status === "running" || status === "starting") {
    return (
      <Badge variant="outline" className="gap-1 border-blue-200 text-blue-700 dark:border-blue-800 dark:text-blue-400">
        <Loader2 className="h-3 w-3 animate-spin" />
        {status === "starting" ? "Starting" : "Running"}
      </Badge>
    );
  }
  if (status === "completed") {
    return (
      <Badge variant="outline" className="gap-1 border-green-200 text-green-700 dark:border-green-800 dark:text-green-400">
        <CheckCircle2 className="h-3 w-3" />
        Completed
      </Badge>
    );
  }
  if (status === "failed") {
    return (
      <Badge variant="outline" className="gap-1 border-red-200 text-red-700 dark:border-red-800 dark:text-red-400">
        <XCircle className="h-3 w-3" />
        Failed
      </Badge>
    );
  }
  return <Badge variant="outline">{status}</Badge>;
}

function AgentMessage({
  session,
  projectId,
}: {
  session: ConversationSession;
  projectId: number;
}) {
  const isActive = session.status === "running" || session.status === "starting";

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-muted-foreground">StrawPot</span>
        <StatusBadge status={session.status} />
        {session.duration_ms !== null && (
          <span className="text-xs text-muted-foreground">
            {formatDuration(session.duration_ms)}
          </span>
        )}
        <span className="text-xs text-muted-foreground">{session.role}</span>
      </div>
      <div className="rounded-lg border border-border bg-muted/30 p-3 text-sm">
        {isActive ? (
          <span className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Working…
          </span>
        ) : session.summary ? (
          <MarkdownContent content={session.summary} className="text-sm text-foreground" />
        ) : (
          <span className="text-muted-foreground italic">
            {session.status === "failed" ? "Session failed without output." : session.status === "stopped" ? "Interrupted." : "No summary available."}
          </span>
        )}
      </div>
      <a
        href={`/projects/${projectId}/sessions/${session.run_id}`}
        target="_blank"
        rel="noopener noreferrer"
        className="flex w-fit items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
      >
        <ExternalLink className="h-3 w-3" />
        View session
      </a>
    </div>
  );
}

function UserMessage({ task }: { task: string }) {
  return (
    <div className="flex flex-col gap-1.5 items-end">
      <span className="text-xs font-medium text-muted-foreground">You</span>
      <div className="max-w-[80%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground">
        <p className="whitespace-pre-wrap">{task}</p>
      </div>
    </div>
  );
}

export default function ConversationView() {
  const { projectId, conversationId } = useParams();
  const pid = Number(projectId);
  const cid = Number(conversationId);
  const [task, setTask] = useState("");
  const [role, setRole] = useState("");
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [showAllFiles, setShowAllFiles] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [fileFilter, setFileFilter] = useState("");
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  // Advanced settings (persist across submissions)
  const [advRuntime, setAdvRuntime] = useState("");
  const [advMemory, setAdvMemory] = useState("");
  const [advSystemPrompt, setAdvSystemPrompt] = useState("");
  const [advMaxDelegations, setAdvMaxDelegations] = useState("");
  const [advCacheDelegations, setAdvCacheDelegations] = useState("");
  const [advCacheMaxEntries, setAdvCacheMaxEntries] = useState("");
  const [advCacheTtl, setAdvCacheTtl] = useState("");
  const [interactive, setInteractive] = useState(false);
  const [askUserResponse, setAskUserResponse] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const prevScrollHeightRef = useRef(0);
  const prevLastSessionIdRef = useRef<string | undefined>(undefined);
  const prevChatLengthRef = useRef(0);
  const titleInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const qc = useQueryClient();

  const { data: projectResources } = useProjectResources(pid);
  const projectRoleNames = (projectResources ?? [])
    .filter((r) => r.type === "roles")
    .map((r) => r.name);
  const config = useProjectConfig(pid);
  const projectFiles = useProjectFiles(pid);
  const defaults = config.data?.merged as {
    runtime?: string; memory?: string;
    cache_delegations?: boolean; cache_max_entries?: number;
    cache_ttl_seconds?: number; max_num_delegations?: number;
  } | undefined;

  // Initial load — no polling yet
  const { data, isLoading, error, fetchPreviousPage, hasPreviousPage, isFetchingPreviousPage } =
    useConversationInfinite(cid);

  // Flatten pages: pages[0]=oldest loaded, pages[last]=newest
  const allSessions = data?.pages.flatMap((p) => p.sessions) ?? [];
  const conversation = data?.pages[data.pages.length - 1];
  const lastSession = allSessions[allSessions.length - 1];
  const hasActiveSession =
    lastSession?.status === "running" || lastSession?.status === "starting";

  // Poll while any session is active (same query key — TanStack merges refetchInterval)
  useConversationInfinite(cid, { refetchInterval: hasActiveSession ? 2000 : false });

  const submit = useSubmitConversationTask(cid);
  const stop = useStopSession();
  const cancelPending = useCancelPendingTask(cid);
  const cancelTask = useCancelQueuedTask(cid);
  const rename = useRenameConversation(pid);
  const { pendingAskUsers, chatMessages, respond } = useSessionWS(
    lastSession?.run_id ?? "",
    hasActiveSession && interactive,
  );

  const roleError =
    role.trim() && !projectRoleNames.includes(role.trim())
      ? "Role not found in installed roles"
      : "";

  const isActive = hasActiveSession;

  // Scroll anchor: restore position when older pages are prepended
  useEffect(() => {
    if (!scrollRef.current) return;
    const delta = scrollRef.current.scrollHeight - prevScrollHeightRef.current;
    if (delta > 0) {
      scrollRef.current.scrollTop += delta;
      prevScrollHeightRef.current = 0;
    }
  }, [data?.pages.length]);

  // Auto-scroll to bottom only when the newest session changes
  useEffect(() => {
    if (!scrollRef.current) return;
    if (lastSession?.run_id !== prevLastSessionIdRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
    prevLastSessionIdRef.current = lastSession?.run_id;
  }, [lastSession?.run_id]);

  // Auto-scroll when new chat messages arrive
  useEffect(() => {
    if (!scrollRef.current) return;
    if (chatMessages.length > prevChatLengthRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
    prevChatLengthRef.current = chatMessages.length;
  }, [chatMessages.length]);

  // IntersectionObserver: auto-load older sessions when sentinel reaches top
  useEffect(() => {
    if (!sentinelRef.current || !scrollRef.current) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && hasPreviousPage && !isFetchingPreviousPage) {
          prevScrollHeightRef.current = scrollRef.current?.scrollHeight ?? 0;
          fetchPreviousPage();
        }
      },
      { root: scrollRef.current, threshold: 0.1 },
    );
    observer.observe(sentinelRef.current);
    return () => observer.disconnect();
  }, [hasPreviousPage, isFetchingPreviousPage, fetchPreviousPage]);

  const agentNames = (projectResources ?? [])
    .filter((r) => r.type === "agents")
    .map((r) => r.name);
  const memoryNames = [
    ...new Set((projectResources ?? []).filter((r) => r.type === "memories").map((r) => r.name)),
    "none",
  ].sort();

  const advRuntimeError = advRuntime.trim() && agentNames.length > 0 && !agentNames.includes(advRuntime.trim())
    ? "Runtime not found in installed agents" : "";
  const advMemoryError = advMemory.trim() && memoryNames.length > 0 && !memoryNames.includes(advMemory.trim())
    ? "Memory not found in installed providers" : "";
  const hasAdvError = !!advRuntimeError || !!advMemoryError;

  // Count active advanced settings for badge indicator
  const advCount = [advRuntime, advMemory, advSystemPrompt, advMaxDelegations, advCacheDelegations, advCacheMaxEntries, advCacheTtl]
    .filter(v => v.trim()).length;

  const toggleFile = (path: string) =>
    setSelectedFiles((prev) =>
      prev.includes(path) ? prev.filter((p) => p !== path) : [...prev, path],
    );

  const handleDragOver = (e: React.DragEvent) => { e.preventDefault(); setIsDragging(true); };
  const handleDragEnter = (e: React.DragEvent) => { e.preventDefault(); setIsDragging(true); };
  const handleDragLeave = (e: React.DragEvent) => { e.preventDefault(); setIsDragging(false); };
  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const files = Array.from(e.dataTransfer.files);
    if (!files.length) return;
    setIsUploading(true);
    try {
      const uploaded = await api.upload<ProjectFile[]>(`/projects/${pid}/files`, files);
      qc.invalidateQueries({ queryKey: queryKeys.projects.files(pid) });
      setSelectedFiles((prev) => {
        const newPaths = uploaded.map((f) => f.path).filter((p) => !prev.includes(p));
        return [...prev, ...newPaths];
      });
    } catch {
      // upload error — silently ignore, files will still appear in picker on next load
    } finally {
      setIsUploading(false);
    }
  };

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = task.trim();
    if (!trimmed || !!roleError || hasAdvError) return;
    const body: Parameters<typeof submit.mutate>[0] = {
      task: trimmed,
      role: role.trim() || undefined,
      context_files: selectedFiles.length > 0 ? selectedFiles : undefined,
      interactive,
      system_prompt: advSystemPrompt.trim() || undefined,
      runtime: advRuntime.trim() || undefined,
      memory: advMemory.trim() || undefined,
      max_num_delegations: advMaxDelegations.trim() ? Number(advMaxDelegations) : undefined,
      cache_delegations: advCacheDelegations ? advCacheDelegations === "true" : undefined,
      cache_max_entries: advCacheMaxEntries.trim() ? Number(advCacheMaxEntries) : undefined,
      cache_ttl_seconds: advCacheTtl.trim() ? Number(advCacheTtl) : undefined,
    };
    submit.mutate(body, {
      onSuccess: () => { setTask(""); setSelectedFiles([]); setShowAllFiles(false); setTimeout(() => textareaRef.current?.focus(), 0); },
    });
  }

  function handleAskUserResponse(pending: AskUserPending, text: string) {
    if (!text.trim()) return;
    respond(pending.request_id, text.trim());
    setAskUserResponse("");
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e as unknown as React.FormEvent);
    }
  }

  function startEditTitle() {
    setTitleDraft(conversation?.title ?? "");
    setEditingTitle(true);
    setTimeout(() => titleInputRef.current?.select(), 0);
  }

  function commitTitle() {
    const trimmed = titleDraft.trim();
    rename.mutate({ conversationId: cid, title: trimmed || null });
    setEditingTitle(false);
  }

  function handleTitleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") { e.preventDefault(); commitTitle(); }
    if (e.key === "Escape") { setEditingTitle(false); }
  }

  if (error) {
    return (
      <div className="flex items-center gap-2 text-destructive">
        <AlertCircle className="h-4 w-4" />
        <span>Error: {(error as Error).message}</span>
      </div>
    );
  }

  const title = conversation?.title ?? `Conversation #${cid}`;

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex flex-shrink-0 items-center justify-between border-b border-border pb-3 mb-4">
        <div className="flex items-center gap-3">
          {editingTitle ? (
            <Input
              ref={titleInputRef}
              value={titleDraft}
              onChange={(e) => setTitleDraft(e.target.value)}
              onBlur={commitTitle}
              onKeyDown={handleTitleKeyDown}
              className="h-7 text-sm font-semibold w-64"
              placeholder={`Conversation #${cid}`}
            />
          ) : (
            <h1
              className="text-sm font-semibold cursor-pointer hover:text-muted-foreground"
              onClick={startEditTitle}
              title="Click to rename"
            >
              {title}
            </h1>
          )}
          <SourceBadge source={conversation?.source} meta={conversation?.source_meta} />
        </div>
        {allSessions.length > 0 && (
          <span className="text-xs text-muted-foreground">
            {allSessions.length} session{allSessions.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {/* Cross-link: parent conversation */}
      {conversation?.parent && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground bg-muted/50 rounded px-3 py-1.5 mb-3">
          <BotMessageSquare className="h-3.5 w-3.5 shrink-0" />
          <span>Spawned from</span>
          <Link
            to={`/imu/${conversation.parent.id}`}
            className="text-primary hover:underline inline-flex items-center gap-1"
          >
            {conversation.parent.title || `imu conversation #${conversation.parent.id}`}
            <ArrowUpRight className="h-3 w-3" />
          </Link>
        </div>
      )}

      {/* Cross-link: child conversations spawned from this one */}
      {conversation?.children && conversation.children.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground bg-muted/50 rounded px-3 py-1.5 mb-3">
          <ExternalLink className="h-3.5 w-3.5 shrink-0" />
          <span>Delegated to:</span>
          {conversation.children.map((child) => (
            <Link
              key={child.id}
              to={`/projects/${child.project_id}/conversations/${child.id}`}
              className="text-primary hover:underline inline-flex items-center gap-1"
            >
              {child.project_name}: {child.title || `#${child.id}`}
              <ArrowUpRight className="h-3 w-3" />
            </Link>
          ))}
        </div>
      )}

      {/* Message list — scrolls within this container */}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-2xl space-y-6 py-4">
          {/* Sentinel at top triggers loading older sessions */}
          <div ref={sentinelRef} className="h-1" />
          {isFetchingPreviousPage && (
            <div className="flex justify-center py-2">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            </div>
          )}
          {!isLoading && allSessions.length === 0 && (
            <p className="text-center text-sm text-muted-foreground py-12">
              Start the conversation by submitting a task below.
            </p>
          )}
          {allSessions.map((session, index) => {
            const isLast = index === allSessions.length - 1;
            return (
              <div key={session.run_id} className="space-y-4">
                {(session.user_task ?? session.task) && <UserMessage task={(session.user_task ?? session.task)!} />}
                {/* Chat messages: live from WS for active session, persisted for completed */}
                {(isLast && hasActiveSession ? chatMessages : session.chat_messages ?? []).map((msg: ChatMessage) => (
                  <div
                    key={msg.id}
                    className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                  >
                    <div
                      className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
                        msg.role === "user"
                          ? "bg-primary text-primary-foreground"
                          : "bg-muted text-foreground"
                      }`}
                    >
                      <MarkdownContent content={msg.text} className="whitespace-pre-wrap" />
                    </div>
                  </div>
                ))}
                <AgentMessage session={session} projectId={pid} />
              </div>
            );
          })}
        </div>
      </div>

      {/* Pending (queued) task indicator */}
      {conversation?.queued_tasks && conversation.queued_tasks.length > 0 && (() => {
        const tasks = conversation.queued_tasks;
        return (
          <div className="flex-shrink-0 border-t border-border bg-background px-4 py-2">
            <div className="mx-auto max-w-2xl space-y-1.5">
              {tasks.map((qt, i) => (
                <div key={qt.id} className="flex items-center gap-2 rounded-lg border border-dashed border-primary/40 bg-primary/5 px-3 py-2">
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-primary flex-shrink-0" />
                  {qt.source !== "user" && (
                    <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-muted text-muted-foreground flex-shrink-0">
                      {qt.source}
                    </span>
                  )}
                  <span className="text-xs text-muted-foreground flex-1 truncate">
                    Queued{tasks.length > 1 ? ` (${i + 1}/${tasks.length})` : ""}:{" "}
                    <span className="text-foreground">{qt.task.split("\n")[0]}</span>
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    className="flex-shrink-0 text-muted-foreground hover:text-destructive"
                    onClick={() => cancelTask.mutate(qt.id)}
                    disabled={cancelTask.isPending}
                  >
                    <X />
                  </Button>
                </div>
              ))}
              {tasks.length > 1 && (
                <div className="flex justify-end">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-6 px-2 text-xs text-muted-foreground hover:text-destructive"
                    onClick={() => cancelPending.mutate()}
                    disabled={cancelPending.isPending}
                  >
                    <X className="h-3 w-3 mr-1" />
                    Cancel all
                  </Button>
                </div>
              )}
            </div>
          </div>
        );
      })()}

      {/* Pending ask_user questions */}
      {pendingAskUsers.length > 0 && (
        <div className="flex-shrink-0 border-t border-border bg-background px-4 pt-3 pb-1">
          <div className="mx-auto max-w-2xl space-y-2">
            {pendingAskUsers.map((pending) => (
              <div key={pending.request_id} className="rounded-lg border border-border bg-muted/30 p-3 space-y-2">
                <MarkdownContent content={pending.question} className="text-sm font-medium" />
                {pending.why && (
                  <MarkdownContent content={pending.why} className="text-xs text-muted-foreground" />
                )}
                {pending.choices && (
                  <div className="flex flex-wrap gap-1.5">
                    {pending.choices.map((choice) => (
                      <Button
                        key={choice}
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => handleAskUserResponse(pending, choice)}
                      >
                        {choice}
                      </Button>
                    ))}
                  </div>
                )}
                <div className="flex gap-2">
                  <Input
                    value={askUserResponse}
                    onChange={(e) => setAskUserResponse(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        handleAskUserResponse(pending, askUserResponse);
                      }
                    }}
                    placeholder="Your answer…"
                    autoFocus
                    className="text-sm"
                  />
                  <Button
                    type="button"
                    size="icon"
                    disabled={!askUserResponse.trim()}
                    onClick={() => handleAskUserResponse(pending, askUserResponse)}
                  >
                    <CornerDownLeft className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Task input */}
      <div className="flex-shrink-0 border-t border-border bg-background pt-4">
        <form onSubmit={handleSubmit} className="mx-auto max-w-2xl space-y-2">
          {/* Textarea with drag-and-drop overlay */}
          <div
            className="relative"
            onDragOver={handleDragOver}
            onDragEnter={handleDragEnter}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <Textarea
              ref={textareaRef}
              value={task}
              onChange={(e) => setTask(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                isActive
                  ? "Queue a follow-up task… (Enter to queue, runs after current session)"
                  : "Describe the next task… (Enter to submit, Shift+Enter for new line, drag & drop files to attach)"
              }
              disabled={submit.isPending}
              className="h-[80px] resize-none overflow-y-auto"
              autoFocus
            />
            {(isDragging || isUploading) && (
              <div className="absolute inset-0 flex items-center justify-center rounded-md border-2 border-dashed border-primary bg-background/80 pointer-events-none">
                {isUploading ? (
                  <span className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin" /> Uploading…
                  </span>
                ) : (
                  <span className="flex items-center gap-2 text-sm text-primary">
                    <Upload className="h-4 w-4" /> Drop to upload &amp; attach
                  </span>
                )}
              </div>
            )}
          </div>

          {/* File attachment picker + badges */}
          {(projectFiles.data ?? []).length > 0 && (
            <div className="space-y-1.5">
              <div className="flex items-center gap-2">
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button type="button" variant="outline" size="sm" className="h-7 text-xs">
                      <Paperclip className="mr-1 h-3 w-3" />
                      Annotate files
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start" className="w-64" onCloseAutoFocus={(e) => e.preventDefault()}>
                    <div className="px-2 py-1.5">
                      <Input
                        placeholder="Filter files…"
                        value={fileFilter}
                        onChange={(e) => setFileFilter(e.target.value)}
                        className="h-7 text-xs"
                        onKeyDown={(e) => e.stopPropagation()}
                      />
                    </div>
                    <div className="max-h-48 overflow-y-auto">
                      {(projectFiles.data ?? [])
                        .filter((f) => f.path.toLowerCase().includes(fileFilter.toLowerCase()))
                        .map((f) => (
                          <DropdownMenuCheckboxItem
                            key={f.path}
                            checked={selectedFiles.includes(f.path)}
                            onCheckedChange={() => toggleFile(f.path)}
                            onSelect={(e) => e.preventDefault()}
                          >
                            <span className="font-mono text-xs">{f.path}</span>
                          </DropdownMenuCheckboxItem>
                        ))}
                    </div>
                  </DropdownMenuContent>
                </DropdownMenu>
                {selectedFiles.length > 0 && (
                  <span className="text-xs text-muted-foreground">{selectedFiles.length} attached</span>
                )}
              </div>
              {selectedFiles.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {(showAllFiles ? selectedFiles : selectedFiles.slice(0, 3)).map((path) => (
                    <Badge key={path} variant="secondary" className="gap-1 font-mono text-xs">
                      <button type="button" onClick={() => toggleFile(path)} className="mr-0.5 rounded-sm hover:bg-muted">
                        <X className="h-3 w-3" />
                      </button>
                      @{path}
                    </Badge>
                  ))}
                  {!showAllFiles && selectedFiles.length > 3 && (
                    <button
                      type="button"
                      onClick={() => setShowAllFiles(true)}
                      className="basis-full text-left text-xs text-muted-foreground hover:text-foreground"
                    >
                      +{selectedFiles.length - 3} more
                    </button>
                  )}
                  {showAllFiles && selectedFiles.length > 3 && (
                    <button
                      type="button"
                      onClick={() => setShowAllFiles(false)}
                      className="basis-full text-left text-xs text-muted-foreground hover:text-foreground"
                    >
                      Show less
                    </button>
                  )}
                </div>
              )}
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between gap-2">
              <div className="flex flex-col gap-1">
                <Input
                  list="datalist-role"
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  placeholder="Default role"
                  className="w-48 text-sm"
                />
                {roleError && (
                  <p className="text-xs text-destructive">{roleError}</p>
                )}
              </div>
              <datalist id="datalist-role">
                {projectRoleNames.map((r) => (
                  <option key={r} value={r} />
                ))}
              </datalist>
              <div className="flex items-center gap-1">
                <Button
                  type="button"
                  variant={interactive ? "secondary" : "ghost"}
                  size="sm"
                  className="h-8 gap-1.5 text-xs text-muted-foreground hover:text-foreground"
                  onClick={() => setInteractive((v) => !v)}
                  title={interactive ? "Interactive: agent can ask questions" : "Auto: agent cannot ask questions"}
                >
                  <MessageSquare className="h-3.5 w-3.5" />
                  {interactive ? "Interactive" : "Auto"}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="relative h-8 w-8 text-muted-foreground hover:text-foreground"
                  onClick={() => setSettingsOpen(true)}
                  title="Advanced options"
                >
                  <Settings className="h-4 w-4" />
                  {advCount > 0 && (
                    <span className="absolute -right-0.5 -top-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-primary text-[9px] text-primary-foreground">
                      {advCount}
                    </span>
                  )}
                </Button>
                {isActive && (
                  <Button
                    type="button"
                    variant="destructive"
                    onClick={() => lastSession && stop.mutate(lastSession.run_id)}
                    disabled={stop.isPending}
                  >
                    {stop.isPending ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Square className="mr-2 h-4 w-4 fill-current" />
                    )}
                    Stop
                  </Button>
                )}
                <Button
                  type="submit"
                  disabled={!task.trim() || submit.isPending || !!roleError || hasAdvError}
                  variant={isActive ? "outline" : "default"}
                  title={isActive ? "Queue task (runs after current session)" : undefined}
                >
                  {submit.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <CornerDownLeft className="h-4 w-4" />
                  )}
                </Button>
              </div>
            </div>
          </div>
        </form>
      </div>

      {/* Advanced settings dialog */}
      <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Advanced Options</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Runtime</Label>
                <Input
                  list="adv-datalist-runtime"
                  value={advRuntime}
                  onChange={(e) => setAdvRuntime(e.target.value)}
                  placeholder={defaults?.runtime ?? "default"}
                  className="text-sm"
                />
                <datalist id="adv-datalist-runtime">
                  {agentNames.map((n) => <option key={n} value={n} />)}
                </datalist>
                {advRuntimeError && <p className="text-xs text-destructive">{advRuntimeError}</p>}
              </div>
              <div className="space-y-2">
                <Label>Memory</Label>
                <Input
                  list="adv-datalist-memory"
                  value={advMemory}
                  onChange={(e) => setAdvMemory(e.target.value)}
                  placeholder={defaults?.memory ?? "dial"}
                  className="text-sm"
                />
                <datalist id="adv-datalist-memory">
                  {memoryNames.map((n) => <option key={n} value={n} />)}
                </datalist>
                {advMemoryError && <p className="text-xs text-destructive">{advMemoryError}</p>}
              </div>
            </div>
            <div className="space-y-2">
              <Label>System Prompt</Label>
              <Textarea
                value={advSystemPrompt}
                onChange={(e) => setAdvSystemPrompt(e.target.value)}
                placeholder="Additional instructions appended to conversation context…"
                rows={3}
                className="text-sm"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Max Delegations</Label>
                <Input
                  type="number"
                  min="0"
                  value={advMaxDelegations}
                  onChange={(e) => setAdvMaxDelegations(e.target.value)}
                  placeholder={defaults?.max_num_delegations ? String(defaults.max_num_delegations) : "0 (unlimited)"}
                  className="h-8 text-xs"
                />
              </div>
              <div className="space-y-2">
                <Label>Cache Delegations</Label>
                <Select
                  value={advCacheDelegations || "__empty__"}
                  onValueChange={(v) => setAdvCacheDelegations(v === "__empty__" ? "" : v)}
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue placeholder={`Default (${defaults?.cache_delegations !== false ? "true" : "false"})`} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__empty__" className="text-muted-foreground">
                      Default ({defaults?.cache_delegations !== false ? "true" : "false"})
                    </SelectItem>
                    <SelectItem value="true">true</SelectItem>
                    <SelectItem value="false">false</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Cache Max Entries</Label>
                <Input
                  type="number"
                  min="0"
                  value={advCacheMaxEntries}
                  onChange={(e) => setAdvCacheMaxEntries(e.target.value)}
                  placeholder={defaults?.cache_max_entries ? String(defaults.cache_max_entries) : "0 (unlimited)"}
                  className="h-8 text-xs"
                />
              </div>
              <div className="space-y-2">
                <Label>Cache TTL (seconds)</Label>
                <Input
                  type="number"
                  min="0"
                  value={advCacheTtl}
                  onChange={(e) => setAdvCacheTtl(e.target.value)}
                  placeholder={defaults?.cache_ttl_seconds ? String(defaults.cache_ttl_seconds) : "0 (unlimited)"}
                  className="h-8 text-xs"
                />
              </div>
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setAdvRuntime(""); setAdvMemory(""); setAdvSystemPrompt("");
                setAdvMaxDelegations(""); setAdvCacheDelegations("");
                setAdvCacheMaxEntries(""); setAdvCacheTtl("");
              }}
            >
              Reset
            </Button>
            <Button size="sm" onClick={() => setSettingsOpen(false)}>Done</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
