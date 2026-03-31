import { cn } from "@/lib/utils";

export const QUICK_ROLES = ["imu", "imu-live"] as const;
export type QuickRole = (typeof QUICK_ROLES)[number];

interface RoleQuickSwitchProps {
  /** Current orchestrator role from config. May not be a QuickRole — non-matching values show no active selection. */
  current: string;
  onSwitch: (role: QuickRole) => void;
  disabled?: boolean;
  /** "sm" = compact (h-7/h-6), "md" = standard (h-8/h-7, default) */
  size?: "sm" | "md";
}

const sizeStyles = {
  sm: { outer: "h-7", button: "h-6 px-2.5" },
  md: { outer: "h-8", button: "h-7 px-3" },
} as const;

export default function RoleQuickSwitch({
  current,
  onSwitch,
  disabled,
  size = "md",
}: RoleQuickSwitchProps) {
  const s = sizeStyles[size];
  return (
    <div
      className={cn(
        "inline-flex items-center rounded-md border border-border bg-muted p-0.5",
        s.outer,
      )}
    >
      {QUICK_ROLES.map((role) => (
        <button
          key={role}
          type="button"
          disabled={disabled}
          onClick={() => onSwitch(role)}
          className={cn(
            "inline-flex items-center justify-center rounded-sm",
            s.button,
            "text-xs font-medium transition-colors",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            "disabled:pointer-events-none disabled:opacity-50",
            current === role
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {role}
        </button>
      ))}
    </div>
  );
}
