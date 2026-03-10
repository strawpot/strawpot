import { useState } from "react";
import { useProjectStats } from "@/hooks/queries/use-stats";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { SuccessRateDonut } from "@/components/charts/SuccessRateDonut";
import { RunFrequencyChart } from "@/components/charts/RunFrequencyChart";
import { DurationTrendsChart } from "@/components/charts/DurationTrendsChart";

const PERIODS = ["7d", "30d", "90d"] as const;

function formatDuration(ms: number | null) {
  if (ms === null) return "—";
  if (ms < 60_000) return `${Math.round(ms / 1000)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}

export function ProjectActivityTab({ projectId }: { projectId: number }) {
  const [period, setPeriod] = useState<string>("30d");
  const { data, isLoading } = useProjectStats(projectId, period);

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <div className="grid gap-4 sm:grid-cols-3">
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
        </div>
        <Skeleton className="h-72" />
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="space-y-6">
      {/* Period selector */}
      <div className="flex gap-1">
        {PERIODS.map((p) => (
          <Button
            key={p}
            size="sm"
            variant={period === p ? "default" : "outline"}
            onClick={() => setPeriod(p)}
          >
            {p}
          </Button>
        ))}
      </div>

      {/* Summary cards */}
      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Total Runs
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{data.total_runs}</div>
            <p className="text-xs text-muted-foreground mt-1">
              {data.completed} completed · {data.failed} failed
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Success Rate
            </CardTitle>
          </CardHeader>
          <CardContent className="h-36">
            <SuccessRateDonut
              completed={data.completed}
              failed={data.failed}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Avg Duration
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">
              {formatDuration(data.avg_duration_ms)}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              per session
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Charts */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Run Frequency</CardTitle>
        </CardHeader>
        <CardContent>
          <RunFrequencyChart data={data.daily} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Duration Trends</CardTitle>
        </CardHeader>
        <CardContent>
          <DurationTrendsChart data={data.daily} />
        </CardContent>
      </Card>
    </div>
  );
}
