import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useProject } from "@/hooks/queries/use-projects";
import { useProjectSessions } from "@/hooks/queries/use-sessions";
import { useProjectResources } from "@/hooks/queries/use-project-resources";
import { useProjectConversations } from "@/hooks/queries/use-conversations";
import { useCreateConversation, useDeleteConversation, useRenameConversation } from "@/hooks/mutations/use-conversations";
import Pagination from "@/components/Pagination";
import SessionTable from "@/components/SessionTable";
import LaunchDialog from "@/components/LaunchDialog";
import ProjectFilesTab from "@/components/ProjectFilesTab";
import ProjectResourcesTab from "@/components/ProjectResourcesTab";
import { ProjectActivityTab } from "@/components/ProjectActivityTab";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { AlertCircle, ArrowLeft, Download, MessageSquare, Pencil, Play, Trash2 } from "lucide-react";
import InstallDialog from "@/components/InstallDialog";
import ProjectDetailSkeleton from "@/components/skeletons/ProjectDetailSkeleton";
import { SourceBadge } from "@/components/SourceBadge";

function EditableTitleCell({
  projectId,
  conversationId,
  title,
  fallback,
}: {
  projectId: number;
  conversationId: number;
  title: string | null;
  fallback: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const rename = useRenameConversation(projectId);

  function start(e: React.MouseEvent) {
    e.stopPropagation();
    setDraft(title ?? "");
    setEditing(true);
    setTimeout(() => inputRef.current?.select(), 0);
  }

  function commit(e: React.SyntheticEvent) {
    e.stopPropagation();
    const trimmed = draft.trim();
    rename.mutate({ conversationId, title: trimmed || null });
    setEditing(false);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") { e.preventDefault(); commit(e); }
    if (e.key === "Escape") { e.stopPropagation(); setEditing(false); }
  }

  if (editing) {
    return (
      <Input
        ref={inputRef}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={handleKeyDown}
        onClick={(e) => e.stopPropagation()}
        className="h-7 text-sm font-medium w-full"
        placeholder={fallback}
      />
    );
  }

  return (
    <div className="flex items-center gap-1.5 group">
      <span className="font-medium">{title ?? fallback}</span>
      <Button
        variant="ghost"
        size="icon"
        className="h-5 w-5 text-muted-foreground hover:text-foreground"
        onClick={start}
        aria-label="Rename"
      >
        <Pencil className="h-3 w-3" />
      </Button>
    </div>
  );
}

function DeleteConversationButton({
  projectId,
  conversationId,
  label,
}: {
  projectId: number;
  conversationId: number;
  label: string;
}) {
  const [confirming, setConfirming] = useState(false);
  const deleteConversation = useDeleteConversation(projectId);

  if (confirming) {
    return (
      <div className="flex justify-end gap-1" onClick={(e) => e.stopPropagation()}>
        <Button
          size="sm"
          variant="destructive"
          disabled={deleteConversation.isPending}
          onClick={(e) => {
            e.stopPropagation();
            deleteConversation.mutate(conversationId, {
              onSuccess: () => setConfirming(false),
              onError: () => setConfirming(false),
            });
          }}
        >
          Confirm
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={(e) => {
            e.stopPropagation();
            setConfirming(false);
          }}
        >
          No
        </Button>
      </div>
    );
  }

  return (
    <Button
      variant="ghost"
      size="icon"
      className="h-7 w-7 text-muted-foreground hover:text-destructive"
      onClick={(e) => {
        e.stopPropagation();
        setConfirming(true);
      }}
      aria-label={`Delete ${label}`}
    >
      <Trash2 className="h-3.5 w-3.5" />
    </Button>
  );
}

const TYPE_LABELS: Record<string, string> = {
  roles: "Role",
  skills: "Skill",
  agents: "Agent",
  memories: "Memory",
};

export default function ProjectDetail() {
  const { projectId } = useParams();
  const pid = Number(projectId);
  const navigate = useNavigate();
  const project = useProject(pid);
  const [sessionPage, setSessionPage] = useState(1);
  const [conversationPage] = useState(1);
  const sessions = useProjectSessions(pid, sessionPage);
  const resources = useProjectResources(pid);
  const conversations = useProjectConversations(pid, conversationPage);
  const createConversation = useCreateConversation();
  const [launchOpen, setLaunchOpen] = useState(false);
  const [installOpen, setInstallOpen] = useState(false);
  const [activeTab, setActiveTab] = useState("conversations");

  const loading = project.isLoading || sessions.isLoading;
  const error = project.error || sessions.error;

  if (loading) {
    return <ProjectDetailSkeleton />;
  }
  if (error) {
    return (
      <div className="flex items-center gap-2 text-destructive">
        <AlertCircle className="h-4 w-4" />
        <span>Error: {error.message}</span>
      </div>
    );
  }
  if (!project.data) {
    return (
      <div className="flex items-center gap-2 text-destructive">
        <AlertCircle className="h-4 w-4" />
        <span>Project not found</span>
      </div>
    );
  }

  const p = project.data;
  const sessionData = sessions.data;
  const sessionList = sessionData?.items ?? [];
  const sessionTotal = sessionData?.total ?? 0;
  const sessionTotalPages = sessionData ? Math.ceil(sessionData.total / sessionData.per_page) : 0;
  const resourceList = resources.data ?? [];

  const resourceCounts = resourceList.reduce<Record<string, number>>((acc, r) => {
    acc[r.type] = (acc[r.type] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Button variant="outline" size="sm" asChild>
            <Link to="/projects">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back
            </Link>
          </Button>
          <h1 className="text-2xl font-bold tracking-tight">{p.display_name}</h1>
        </div>
        <div className="flex gap-2">
          <Button
            disabled={!p.dir_exists || createConversation.isPending}
            onClick={() => {
              createConversation.mutate(
                { project_id: pid },
                {
                  onSuccess: (conv) =>
                    navigate(`/projects/${pid}/conversations/${conv.id}`),
                },
              );
            }}
          >
            <MessageSquare className="mr-2 h-4 w-4" />
            New Conversation
          </Button>
          <Button variant="outline" onClick={() => setLaunchOpen(true)} disabled={!p.dir_exists}>
            <Play className="mr-2 h-4 w-4" />
            Launch Session
          </Button>
          <Button
            variant="outline"
            onClick={() => { setActiveTab("resources"); setInstallOpen(true); }}
          >
            <Download className="mr-2 h-4 w-4" />
            Install Resource
          </Button>
        </div>
      </div>

      <Card>
        <CardContent className="pt-6">
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="font-medium text-muted-foreground">Directory</dt>
            <dd className="flex items-center gap-2 break-all">
              {p.working_dir}
              {p.dir_exists ? (
                <Badge
                  variant="outline"
                  className="border-green-200 bg-green-50 text-xs text-green-700 dark:border-green-800 dark:bg-green-950 dark:text-green-400"
                >
                  OK
                </Badge>
              ) : (
                <Badge
                  variant="outline"
                  className="border-orange-200 bg-orange-50 text-xs text-orange-700 dark:border-orange-800 dark:bg-orange-950 dark:text-orange-400"
                >
                  Missing
                </Badge>
              )}
            </dd>
            <dt className="font-medium text-muted-foreground">Created</dt>
            <dd>{new Date(p.created_at).toLocaleString()}</dd>
            <dt className="font-medium text-muted-foreground">Resources</dt>
            <dd>
              {resourceList.length === 0 ? (
                <span className="text-sm text-muted-foreground">None installed</span>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(resourceCounts).map(([type, count]) => (
                    <Badge
                      key={type}
                      variant="secondary"
                      className="cursor-pointer text-xs"
                      onClick={() => setActiveTab("resources")}
                    >
                      {count} {count === 1 ? (TYPE_LABELS[type] ?? type) : `${TYPE_LABELS[type] ?? type}s`}
                    </Badge>
                  ))}
                </div>
              )}
            </dd>
          </dl>
        </CardContent>
      </Card>

      <LaunchDialog
        projectId={pid}
        open={launchOpen}
        onOpenChange={setLaunchOpen}
      />

      <InstallDialog
        open={installOpen}
        onOpenChange={setInstallOpen}
        projectId={pid}
      />

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="conversations">
            Conversations ({conversations.data?.total ?? 0})
          </TabsTrigger>
          <TabsTrigger value="sessions">
            Sessions ({sessionTotal})
          </TabsTrigger>
          <TabsTrigger value="activity">Activity</TabsTrigger>
          <TabsTrigger value="resources">
            Resources ({resourceList.length})
          </TabsTrigger>
          <TabsTrigger value="files">Files</TabsTrigger>
        </TabsList>

        <TabsContent value="sessions" className="mt-4 space-y-3">
          {sessionTotal === 0 ? (
            <p className="text-sm italic text-muted-foreground">
              No sessions yet.
            </p>
          ) : (
            <>
              <Card>
                <CardContent className="p-0">
                  <SessionTable sessions={sessionList} />
                </CardContent>
              </Card>
              <Pagination
                page={sessionPage}
                totalPages={sessionTotalPages}
                onPageChange={setSessionPage}
              />
            </>
          )}
        </TabsContent>

        <TabsContent value="conversations" className="mt-4 space-y-3">
          {(conversations.data?.items ?? []).length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <p className="text-sm text-muted-foreground mb-4">
                No conversations yet.
              </p>
              <Button
                disabled={!p.dir_exists || createConversation.isPending}
                onClick={() => {
                  createConversation.mutate(
                    { project_id: pid },
                    {
                      onSuccess: (conv) =>
                        navigate(`/projects/${pid}/conversations/${conv.id}`),
                    },
                  );
                }}
              >
                <MessageSquare className="mr-2 h-4 w-4" />
                New Conversation
              </Button>
            </div>
          ) : (
            <Card>
              <CardContent className="p-0">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-xs text-muted-foreground">
                      <th className="px-4 py-2 font-medium">Title</th>
                      <th className="px-4 py-2 font-medium">Sessions</th>
                      <th className="px-4 py-2 font-medium">Last activity</th>
                      <th className="px-4 py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {(conversations.data?.items ?? []).map((conv) => (
                      <tr
                        key={conv.id}
                        className="cursor-pointer border-b border-border last:border-0 hover:bg-muted/50"
                        onClick={() =>
                          navigate(`/projects/${pid}/conversations/${conv.id}`)
                        }
                      >
                        <td className="px-4 py-2">
                          <div className="flex items-center gap-2">
                            <EditableTitleCell
                              projectId={pid}
                              conversationId={conv.id}
                              title={conv.title}
                              fallback={`Conversation #${conv.id}`}
                            />
                            <SourceBadge source={conv.source} meta={conv.source_meta} />
                          </div>
                        </td>
                        <td className="px-4 py-2 text-muted-foreground">
                          {conv.session_count}
                        </td>
                        <td className="px-4 py-2 text-muted-foreground">
                          {conv.last_activity
                            ? new Date(conv.last_activity).toLocaleString()
                            : "—"}
                        </td>
                        <td className="px-4 py-2 text-right">
                          <DeleteConversationButton
                            projectId={pid}
                            conversationId={conv.id}
                            label={conv.title ?? `Conversation #${conv.id}`}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="activity" className="mt-4">
          <ProjectActivityTab projectId={pid} />
        </TabsContent>

        <TabsContent value="resources" className="mt-4">
          <ProjectResourcesTab
            projectId={pid}
            installOpen={installOpen}
            onInstallOpenChange={setInstallOpen}
          />
        </TabsContent>

        <TabsContent value="files" className="mt-4">
          <ProjectFilesTab projectId={pid} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
