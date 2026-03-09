import { Link } from "react-router-dom";
import { useProjects } from "@/hooks/queries/use-projects";
import { useRunningSessions, useRecentSessions } from "@/hooks/queries/use-sessions";
import SessionTable from "@/components/SessionTable";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AlertCircle, FolderKanban } from "lucide-react";
import ActiveAgentsPanel from "@/components/ActiveAgentsPanel";
import DashboardSkeleton from "@/components/skeletons/DashboardSkeleton";

export default function Dashboard() {
  const projects = useProjects();
  const running = useRunningSessions();
  const recent = useRecentSessions();

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
          <div className="grid grid-cols-[repeat(auto-fill,minmax(280px,1fr))] gap-3">
            {projectList.map((p) => (
              <Link key={p.id} to={`/projects/${p.id}`} className="group">
                <Card className="transition-colors group-hover:border-foreground/20">
                  <CardHeader className="pb-2">
                    <CardTitle className="flex items-center gap-2 text-base">
                      <FolderKanban className="h-4 w-4 text-muted-foreground" />
                      {p.display_name}
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="break-all text-sm text-muted-foreground">
                      {p.working_dir}
                    </p>
                    <div className="mt-2 flex gap-1.5">
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
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
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

