import { useCallback, useEffect, useRef } from "react";

/** Minimum ms between accepted submits. */
const DEBOUNCE_MS = 300;

/** Window for rejecting duplicate messages (2× debounce). */
const DUPLICATE_WINDOW_MS = DEBOUNCE_MS * 2;

/**
 * Guard against duplicate form submissions.
 *
 * Three layers:
 * 1. **Pending gate** – blocks while a mutation is in-flight.
 * 2. **Debounce** – rejects submits within {@link DEBOUNCE_MS} of the last.
 * 3. **Duplicate check** – rejects the same message within {@link DUPLICATE_WINDOW_MS}.
 */
export function useSubmitGuard(scopeKey?: string | number) {
  const lastTimeRef = useRef(0);
  const lastMessageRef = useRef("");

  // Reset refs when the conversation/session identity changes so stale
  // state from a previous scope doesn't block legitimate submits.
  useEffect(() => {
    lastTimeRef.current = 0;
    lastMessageRef.current = "";
  }, [scopeKey]);

  const trySubmit = useCallback(
    (message: string, isPending: boolean): boolean => {
      if (isPending) return false;

      const now = Date.now();
      const elapsed = now - lastTimeRef.current;

      if (elapsed < DEBOUNCE_MS) return false;

      if (message === lastMessageRef.current && elapsed < DUPLICATE_WINDOW_MS) {
        return false;
      }

      lastTimeRef.current = now;
      lastMessageRef.current = message;
      return true;
    },
    [],
  );

  return { trySubmit };
}
