import { Link } from "react-router-dom";
import { useProjects } from "@/hooks/queries/use-projects";
import { useRunningSessions, useRecentSessions } from "@/hooks/queries/use-sessions";
import { useRecentConversations } from "@/hooks/queries/use-conversations";
import SessionTable from "@/components/SessionTable";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { AlertCircle } from "lucide-react";
import ActiveAgentsPanel from "@/components/ActiveAgentsPanel";
import DashboardSkeleton from "@/components/skeletons/DashboardSkeleton";

export default function Dashboard() {
  const projects = useProjects();
  const running = useRunningSessions();
  const recent = useRecentSessions();
  const recentConversations = useRecentConversations(10);

  const loading = projects.isLoading || running.isLoading || recent.isLoading;
  const error = projects.error || running.error || recent.error;

  if (loading) return <DashboardSkeleton />;
  if (error) {
    return (
      <div className="flex items-center gap-2 text-destructive">
        <AlertCircle className="h-4 w-4" />
        <span>Error: {error.message}</span>
      </div>
    );
  }

  const projectList = projects.data ?? [];
  const runningSessions = running.data?.items ?? [];
  const recentSessions = recent.data?.items ?? [];

  const projectNames = new Map<number, string>();
  for (const p of projectList) {
    projectNames.set(p.id, p.display_name);
  }

  const runningByProject = new Map<number, number>();
  for (const s of runningSessions) {
    runningByProject.set(
      s.project_id,
      (runningByProject.get(s.project_id) ?? 0) + 1,
    );
  }

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>

      {/* Active Agents */}
      <ActiveAgentsPanel />

      {/* Projects */}
      <section className="space-y-3">
        <h2 className="text-sm font-medium text-muted-foreground">
          Projects ({projectList.length})
        </h2>
        {projectList.length === 0 ? (
          <p className="text-sm italic text-muted-foreground">
            No projects registered.
          </p>
        ) : (
          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Directory</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {projectList.slice(0, 10).map((p) => (
                    <TableRow key={p.id}>
                      <TableCell>
                        <Link
                          to={`/projects/${p.id}`}
                          className="text-sm font-medium text-primary underline-offset-4 hover:underline"
                        >
                          {p.display_name}
                        </Link>
                      </TableCell>
                      <TableCell className="max-w-[400px] truncate text-sm text-muted-foreground font-mono">
                        {p.working_dir}
                      </TableCell>
                      <TableCell>
                        <div className="flex gap-1.5">
                          {!p.dir_exists && (
                            <Badge
                              variant="outline"
                              className="border-orange-200 bg-orange-50 text-xs text-orange-700 dark:border-orange-800 dark:bg-orange-950 dark:text-orange-400"
                            >
                              Directory missing
                            </Badge>
                          )}
                          {(runningByProject.get(p.id) ?? 0) > 0 && (
                            <Badge
                              variant="outline"
                              className="border-green-200 bg-green-50 text-xs text-green-700 dark:border-green-800 dark:bg-green-950 dark:text-green-400"
                            >
                              <span className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-green-500" />
                              {runningByProject.get(p.id)} running
                            </Badge>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                  {projectList.length > 10 && (
                    <TableRow>
                      <TableCell colSpan={3} className="text-center">
                        <Link
                          to="/projects"
                          className="text-sm text-muted-foreground underline-offset-4 hover:underline"
                        >
                          +{projectList.length - 10} more — view all projects
                        </Link>
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        )}
      </section>

      {/* Running Sessions */}
      {runningSessions.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-medium text-muted-foreground">
            Running Sessions ({runningSessions.length})
          </h2>
          <Card>
            <CardContent className="p-0">
              <SessionTable
                sessions={runningSessions}
                projectNames={projectNames}
              />
            </CardContent>
          </Card>
        </section>
      )}

      {/* Recent Conversations */}
      {(recentConversations.data ?? []).length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-medium text-muted-foreground">
            Recent Conversations
          </h2>
          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Title</TableHead>
                    <TableHead>Project</TableHead>
                    <TableHead>Sessions</TableHead>
                    <TableHead>Last Activity</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(recentConversations.data ?? []).map((conv) => (
                    <TableRow key={conv.id}>
                      <TableCell>
                        <Link
                          to={`/projects/${conv.project_id}/conversations/${conv.id}`}
                          className="text-sm font-medium text-primary underline-offset-4 hover:underline"
                        >
                          {conv.title ?? `Conversation #${conv.id}`}
                        </Link>
                      </TableCell>
                      <TableCell>
                        <Link
                          to={`/projects/${conv.project_id}`}
                          className="text-sm text-primary underline-offset-4 hover:underline"
                        >
                          {conv.project_name}
                        </Link>
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {conv.session_count}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {conv.last_activity
                          ? new Date(conv.last_activity).toLocaleString()
                          : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </section>
      )}

      {/* Recent Sessions */}
      <section className="space-y-3">
        <h2 className="text-sm font-medium text-muted-foreground">
          Recent Sessions
        </h2>
        {recentSessions.length === 0 ? (
          <p className="text-sm italic text-muted-foreground">
            No sessions yet.
          </p>
        ) : (
          <Card>
            <CardContent className="p-0">
              <SessionTable
                sessions={recentSessions}
                projectNames={projectNames}
              />
            </CardContent>
          </Card>
        )}
      </section>
    </div>
  );
}

