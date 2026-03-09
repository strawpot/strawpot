import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useProject } from "@/hooks/queries/use-projects";
import { useProjectSessions } from "@/hooks/queries/use-sessions";
import SessionTable from "@/components/SessionTable";
import LaunchDialog from "@/components/LaunchDialog";
import ProjectFilesTab from "@/components/ProjectFilesTab";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { AlertCircle, ArrowLeft, Play } from "lucide-react";
import ProjectDetailSkeleton from "@/components/skeletons/ProjectDetailSkeleton";

export default function ProjectDetail() {
  const { projectId } = useParams();
  const pid = Number(projectId);
  const project = useProject(pid);
  const sessions = useProjectSessions(pid);
  const [launchOpen, setLaunchOpen] = useState(false);

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
  const sessionList = sessions.data ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">{p.display_name}</h1>
        <div className="flex gap-2">
          <Button onClick={() => setLaunchOpen(true)} disabled={!p.dir_exists}>
            <Play className="mr-2 h-4 w-4" />
            Launch Session
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
          </dl>
        </CardContent>
      </Card>

      <LaunchDialog
        projectId={pid}
        open={launchOpen}
        onOpenChange={setLaunchOpen}
      />

      <Tabs defaultValue="sessions">
        <TabsList>
          <TabsTrigger value="sessions">
            Sessions ({sessionList.length})
          </TabsTrigger>
          <TabsTrigger value="files">Files</TabsTrigger>
        </TabsList>

        <TabsContent value="sessions" className="mt-4 space-y-3">
          {sessionList.length === 0 ? (
            <p className="text-sm italic text-muted-foreground">
              No sessions yet.
            </p>
          ) : (
            <Card>
              <CardContent className="p-0">
                <SessionTable sessions={sessionList} />
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="files" className="mt-4">
          <ProjectFilesTab projectId={pid} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
