import { cn } from "@/lib/utils";

export default function ViewToggle({
  view,
  onChange,
}: {
  view: "markdown" | "raw";
  onChange: (v: "markdown" | "raw") => void;
}) {
  return (
    <div className="mb-3 flex gap-1">
      <button
        className={cn(
          "rounded px-2 py-1 text-xs font-medium",
          view === "markdown"
            ? "bg-primary text-primary-foreground"
            : "bg-muted text-muted-foreground hover:text-foreground",
        )}
        onClick={() => onChange("markdown")}
      >
        Markdown
      </button>
      <button
        className={cn(
          "rounded px-2 py-1 text-xs font-medium",
          view === "raw"
            ? "bg-primary text-primary-foreground"
            : "bg-muted text-muted-foreground hover:text-foreground",
        )}
        onClick={() => onChange("raw")}
      >
        Raw
      </button>
    </div>
  );
}
