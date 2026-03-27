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
 * - Gradient fade overlay when collapsed
 * - "Show more" / "Show less" toggle (keyboard-accessible)
 * - Smooth CSS max-height transition
 * - Scrolls the message top into view on collapse
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
  const [needsCollapse, setNeedsCollapse] = useState(false);
  const [collapsed, setCollapsed] = useState(true);
  const [contentHeight, setContentHeight] = useState<number>(0);
  const [extraLines, setExtraLines] = useState<number>(0);

  // Measure after render and on resize
  useLayoutEffect(() => {
    const el = contentRef.current;
    if (!el) return;

    const measure = () => {
      const h = el.scrollHeight;
      setContentHeight(h);
      const exceeds = h > COLLAPSE_THRESHOLD_PX;
      setNeedsCollapse(exceeds);
      if (exceeds) {
        // Estimate hidden lines: ~20px per line of rendered text
        const hiddenPx = h - PREVIEW_HEIGHT_PX;
        setExtraLines(Math.max(0, Math.round(hiddenPx / 20)));
      }
    };

    measure();

    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [children]);

  const toggle = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      // When collapsing, scroll the message top into view
      if (next && wrapperRef.current) {
        requestAnimationFrame(() => {
          wrapperRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
        });
      }
      return next;
    });
  }, []);

  // Short messages: render as-is
  if (!needsCollapse) {
    return (
      <div ref={contentRef} className={className}>
        {children}
      </div>
    );
  }

  return (
    <div ref={wrapperRef} className={cn("relative", className)}>
      {/* Content container with animated max-height */}
      <div
        ref={contentRef}
        className="overflow-hidden transition-[max-height] duration-300 ease-in-out"
        style={{
          maxHeight: collapsed ? `${PREVIEW_HEIGHT_PX}px` : `${contentHeight}px`,
        }}
      >
        {children}
      </div>

      {/* Gradient fade overlay when collapsed */}
      {collapsed && (
        <div
          className="pointer-events-none absolute bottom-6 left-0 right-0 h-16"
          style={{
            background: `linear-gradient(to bottom, transparent, ${gradientColor})`,
          }}
        />
      )}

      {/* Toggle button */}
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
    </div>
  );
}
