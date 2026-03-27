import { useCallback, useLayoutEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { ChevronDown, ChevronUp } from "lucide-react";

/** Rendered pixel height above which messages auto-collapse. */
const COLLAPSE_THRESHOLD_PX = 500;
/** Collapsed preview height in pixels (~6-8 lines of text). */
const PREVIEW_HEIGHT_PX = 160;

/**
 * Wraps a message balloon's content and auto-collapses it when the
 * rendered height exceeds COLLAPSE_THRESHOLD_PX.
 *
 * Uses a single DOM tree so the ResizeObserver ref is always stable,
 * regardless of whether the content is short or long.
 */
export default function CollapsibleMessage({
  children,
  className,
  gradientColor = "var(--color-muted)",
}: {
  children: React.ReactNode;
  className?: string;
  /** CSS color for the gradient fade. Should match the parent bubble background. */
  gradientColor?: string;
}) {
  const contentRef = useRef<HTMLDivElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [collapsed, setCollapsed] = useState(true);
  const [contentHeight, setContentHeight] = useState(0);

  const needsCollapse = contentHeight > COLLAPSE_THRESHOLD_PX;
  const extraLines = needsCollapse
    ? Math.max(0, Math.round((contentHeight - PREVIEW_HEIGHT_PX) / 20))
    : 0;

  // Measure content height after render and track resize.
  // The ResizeObserver keeps contentHeight in sync so the expanded
  // max-height constraint tracks with actual content (e.g. lazy images).
  useLayoutEffect(() => {
    const el = contentRef.current;
    if (!el) return;

    const measure = () => setContentHeight(el.scrollHeight);
    measure();

    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []); // ResizeObserver handles all subsequent size changes

  const toggle = useCallback(() => {
    if (!collapsed && wrapperRef.current) {
      requestAnimationFrame(() => {
        wrapperRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      });
    }
    setCollapsed((prev) => !prev);
  }, [collapsed]);

  return (
    <div ref={wrapperRef} className={cn(needsCollapse && "relative", className)}>
      <div
        ref={contentRef}
        data-testid="collapsible-content"
        className={cn(
          needsCollapse &&
            "overflow-hidden transition-[max-height] duration-300 ease-in-out",
        )}
        style={
          needsCollapse
            ? { maxHeight: collapsed ? `${PREVIEW_HEIGHT_PX}px` : `${contentHeight}px` }
            : undefined
        }
      >
        {children}
      </div>

      {needsCollapse && collapsed && (
        <div
          data-testid="gradient-overlay"
          className="pointer-events-none absolute bottom-6 left-0 right-0 h-16"
          style={{
            background: `linear-gradient(to bottom, transparent, ${gradientColor})`,
          }}
        />
      )}

      {needsCollapse && (
        <button
          type="button"
          onClick={toggle}
          className={cn(
            "flex w-full items-center justify-center gap-1 pt-1 pb-0.5",
            "text-xs text-muted-foreground hover:text-foreground",
            "cursor-pointer rounded-b-lg transition-colors",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
          )}
          aria-expanded={!collapsed}
        >
          {collapsed ? (
            <>
              <ChevronDown className="h-3 w-3" />
              Show more
              {extraLines > 0 && (
                <span className="text-muted-foreground/70">
                  (~{extraLines} more lines)
                </span>
              )}
            </>
          ) : (
            <>
              <ChevronUp className="h-3 w-3" />
              Show less
            </>
          )}
        </button>
      )}
    </div>
  );
}
