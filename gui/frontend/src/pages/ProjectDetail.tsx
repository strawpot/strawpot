import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useProject } from "@/hooks/queries/use-projects";
import { useProjectSessions } from "@/hooks/queries/use-sessions";
import { useProjectResources } from "@/hooks/queries/use-project-resources";
import Pagination from "@/components/Pagination";
import SessionTable from "@/components/SessionTable";
import LaunchDialog from "@/components/LaunchDialog";
import ProjectFilesTab from "@/components/ProjectFilesTab";
import ProjectResourcesTab from "@/components/ProjectResourcesTab";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { AlertCircle, ArrowLeft, Download, Play } from "lucide-react";
import InstallDialog from "@/components/InstallDialog";
import ProjectDetailSkeleton from "@/components/skeletons/ProjectDetailSkeleton";

const TYPE_LABELS: Record<string, string> = {
  roles: "Role",
  skills: "Skill",
  agents: "Agent",
  memories: "Memory",
};

export default function ProjectDetail() {
  const { projectId } = useParams();
  const pid = Number(projectId);
  const project = useProject(pid);
  const [sessionPage, setSessionPage] = useState(1);
  const sessions = useProjectSessions(pid, sessionPage);
  const resources = useProjectResources(pid);
  const [launchOpen, setLaunchOpen] = useState(false);
  const [installOpen, setInstallOpen] = useState(false);
  const [activeTab, setActiveTab] = useState("sessions");

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
        <h1 className="text-2xl font-bold tracking-tight">{p.display_name}</h1>
        <div className="flex gap-2">
          <Button onClick={() => setLaunchOpen(true)} disabled={!p.dir_exists}>
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
          <Button variant="outline" asChild>
            <Link to="/projects">
              <ArrowLeft className="mr-2 h-4 w-4" />
              Back
            </Link>
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
          <TabsTrigger value="sessions">
            Sessions ({sessionTotal})
          </TabsTrigger>
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
