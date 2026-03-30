import { useCallback, useRef } from "react";

const DEBOUNCE_MS = 300;

/**
 * Guard against duplicate form submissions.
 *
 * Three layers of protection:
 * 1. **Pending gate** – blocks while a mutation is already in-flight.
 * 2. **Debounce** – rejects calls within 300 ms of the last accepted submit.
 * 3. **Duplicate message check** – rejects if the text matches the most
 *    recently submitted message (within the debounce window).
 *    Callers are responsible for trimming before calling `trySubmit`.
 *
 * Returns `true` when the submit is allowed, `false` when it should be
 * suppressed. The caller is responsible for calling `submit.mutate()` only
 * when `trySubmit` returns `true`.
 */
export function useSubmitGuard() {
  const lastSubmitTimeRef = useRef(0);
  const lastSubmitMessageRef = useRef("");

  const trySubmit = useCallback(
    (message: string, isPending: boolean): boolean => {
      if (isPending) return false;

      const now = Date.now();
      const elapsed = now - lastSubmitTimeRef.current;

      // Debounce: reject if within cooldown window
      if (elapsed < DEBOUNCE_MS) return false;

      // Duplicate check: reject the same message within a wider window
      // (2× debounce) to catch re-submissions that slip past the debounce.
      if (
        message === lastSubmitMessageRef.current &&
        elapsed < DEBOUNCE_MS * 2
      ) {
        return false;
      }

      lastSubmitTimeRef.current = now;
      lastSubmitMessageRef.current = message;
      return true;
    },
    [],
  );

  return { trySubmit };
}
