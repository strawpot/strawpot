import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import type { DailyStats } from "@/api/types";

interface Props {
  data: DailyStats[];
}

function formatDate(date: string) {
  const d = new Date(date + "T00:00:00");
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function formatDuration(ms: number) {
  if (ms < 60_000) return `${Math.round(ms / 1000)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}

export function DurationTrendsChart({ data }: Props) {
  const filtered = data.filter((d) => d.avg_duration_ms !== null);

  if (filtered.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center text-muted-foreground">
        No data
      </div>
    );
  }

  // Convert to minutes for display
  const chartData = data.map((d) => ({
    ...d,
    avg_minutes: d.avg_duration_ms !== null ? d.avg_duration_ms / 60_000 : null,
  }));

  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={chartData} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="hsl(var(--border))"
          vertical={false}
        />
        <XAxis
          dataKey="date"
          tickFormatter={formatDate}
          tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }}
          tickLine={false}
          axisLine={false}
        />
        <YAxis
          tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }}
          tickLine={false}
          axisLine={false}
          tickFormatter={(v) => `${v.toFixed(0)}m`}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "hsl(var(--popover))",
            color: "hsl(var(--popover-foreground))",
            border: "1px solid hsl(var(--border))",
            borderRadius: "6px",
            fontSize: 13,
          }}
          labelFormatter={(label) => formatDate(String(label))}
          formatter={(value) => [
            formatDuration(Number(value) * 60_000),
            "Avg Duration",
          ]}
        />
        <Line
          type="monotone"
          dataKey="avg_minutes"
          name="Avg Duration"
          stroke="#1565c0"
          strokeWidth={2}
          dot={{ r: 3, fill: "#1565c0" }}
          connectNulls
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
