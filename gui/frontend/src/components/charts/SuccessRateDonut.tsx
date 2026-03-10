import { PieChart, Pie, Cell, ResponsiveContainer } from "recharts";

interface Props {
  completed: number;
  failed: number;
}

export function SuccessRateDonut({ completed, failed }: Props) {
  const total = completed + failed;

  if (total === 0) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="relative h-32 w-32">
          <svg viewBox="0 0 100 100" className="h-full w-full">
            <circle
              cx="50"
              cy="50"
              r="40"
              fill="none"
              stroke="hsl(var(--muted))"
              strokeWidth="12"
            />
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-sm text-muted-foreground">N/A</span>
          </div>
        </div>
      </div>
    );
  }

  const rate = Math.round((completed / total) * 1000) / 10;
  const data = [
    { name: "Completed", value: completed },
    { name: "Failed", value: failed },
  ];
  const COLORS = ["#2e7d32", "#c62828"];

  return (
    <div className="relative flex h-full items-center justify-center">
      <ResponsiveContainer width={140} height={140}>
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={40}
            outerRadius={56}
            dataKey="value"
            strokeWidth={0}
          >
            {data.map((_, i) => (
              <Cell key={i} fill={COLORS[i]} />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="text-lg font-semibold">{rate}%</span>
      </div>
    </div>
  );
}
