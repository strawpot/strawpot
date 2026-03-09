import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";

const SEQUENCE_TIMEOUT_MS = 500;

interface UseKeyboardShortcutsOptions {
  onCommandPalette: () => void;
  onShortcutsHelp: () => void;
}

export function useKeyboardShortcuts({
  onCommandPalette,
  onShortcutsHelp,
}: UseKeyboardShortcutsOptions) {
  const navigate = useNavigate();
  const pendingKey = useRef<string | null>(null);
  const pendingTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      // Suppress when focus is in an input-like element
      const target = e.target as HTMLElement;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.isContentEditable
      ) {
        return;
      }

      // Cmd+K / Ctrl+K — command palette
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        onCommandPalette();
        return;
      }

      // Ignore if modifier keys are held (except for Cmd+K above)
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      // ? — shortcuts help
      if (e.key === "?") {
        e.preventDefault();
        onShortcutsHelp();
        return;
      }

      // Two-key sequences: g+d, g+p
      if (pendingKey.current === "g") {
        pendingKey.current = null;
        clearTimeout(pendingTimer.current);

        if (e.key === "d") {
          e.preventDefault();
          navigate("/");
          return;
        }
        if (e.key === "p") {
          e.preventDefault();
          navigate("/projects");
          return;
        }
      }

      if (e.key === "g") {
        pendingKey.current = "g";
        pendingTimer.current = setTimeout(() => {
          pendingKey.current = null;
        }, SEQUENCE_TIMEOUT_MS);
        return;
      }
    }

    document.addEventListener("keydown", handler);
    return () => {
      document.removeEventListener("keydown", handler);
      clearTimeout(pendingTimer.current);
    };
  }, [navigate, onCommandPalette, onShortcutsHelp]);
}
