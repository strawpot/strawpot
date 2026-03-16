import { Globe, Calendar, MessageCircle, Hash, Radio } from "lucide-react";

const SOURCE_CONFIG: Record<string, { icon: typeof Globe; label: string }> = {
  telegram: { icon: MessageCircle, label: "Telegram" },
  slack: { icon: Hash, label: "Slack" },
  discord: { icon: Hash, label: "Discord" },
  scheduler: { icon: Calendar, label: "Scheduler" },
  webhook: { icon: Radio, label: "Webhook" },
};

export function SourceBadge({ source, meta }: { source: string | null | undefined; meta?: string | null }) {
  if (!source) return null;
  const config = SOURCE_CONFIG[source] ?? { icon: Globe, label: source };
  const Icon = config.icon;
  const display = meta || config.label;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground"
      title={meta ? `via ${config.label}: ${meta}` : `via ${config.label}`}
    >
      <Icon className="h-3 w-3" />
      {display}
    </span>
  );
}
