import { useCallback, useRef } from "react";
import type React from "react";

/**
 * Shell-style prompt history navigation for textarea inputs.
 *
 * Keeps an in-memory, conversation-scoped list of previously submitted prompts.
 * Up/Down arrow keys navigate the history when the cursor is at the
 * text boundary (start for Up, end for Down). Multiline text is handled
 * naturally — arrow keys only trigger history navigation when already at
 * the first/last line boundary.
 */

export interface UsePromptHistoryOptions {
  /** Current textarea value. */
  text: string;
  /** Setter for the textarea value. */
  setText: (value: string) => void;
}

export interface UsePromptHistoryReturn {
  /** Attach to onKeyDown on the textarea. */
  handleHistoryKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  /** Call with the submitted prompt text (before clearing the input). */
  addToHistory: (prompt: string) => void;
}

/**
 * Returns `true` when the cursor sits on the **first** line of a textarea.
 *
 * "First line" means everything before the first `\n` (or the entire text
 * if there are no newlines).  We check that `selectionStart` falls within
 * that range (0 … firstNewline-inclusive).
 */
function isOnFirstLine(el: HTMLTextAreaElement): boolean {
  const pos = el.selectionStart;
  const firstNewline = el.value.indexOf("\n");
  // No newlines → always on the first (and only) line.
  if (firstNewline === -1) return true;
  return pos <= firstNewline;
}

/**
 * Returns `true` when the cursor sits on the **last** line of a textarea.
 */
function isOnLastLine(el: HTMLTextAreaElement): boolean {
  const pos = el.selectionStart;
  const lastNewline = el.value.lastIndexOf("\n");
  // No newlines → always on the last (and only) line.
  if (lastNewline === -1) return true;
  return pos > lastNewline;
}

export function usePromptHistory({
  text,
  setText,
}: UsePromptHistoryOptions): UsePromptHistoryReturn {
  // History entries ordered oldest → newest.
  const historyRef = useRef<string[]>([]);
  // Index into history: -1 means "not navigating" (showing current draft).
  const indexRef = useRef(-1);
  // Stashed current input when user starts navigating up.
  const draftRef = useRef("");
  // Ref to current text so handleHistoryKeyDown stays stable across re-renders.
  const textRef = useRef(text);
  textRef.current = text;

  const addToHistory = useCallback((prompt: string) => {
    const trimmed = prompt.trim();
    if (!trimmed) return;
    // Avoid consecutive duplicates.
    const hist = historyRef.current;
    if (hist.length === 0 || hist[hist.length - 1] !== trimmed) {
      hist.push(trimmed);
    }
    // Reset navigation state.
    indexRef.current = -1;
    draftRef.current = "";
  }, []);

  const handleHistoryKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      const el = e.currentTarget;
      const hist = historyRef.current;

      if (e.key === "ArrowUp") {
        // Only intercept when on the first line (cursor hasn't crossed a newline).
        if (!isOnFirstLine(el)) return;
        if (hist.length === 0) return;

        e.preventDefault();

        if (indexRef.current === -1) {
          // Starting navigation — stash current input.
          draftRef.current = textRef.current;
          indexRef.current = hist.length - 1;
        } else if (indexRef.current > 0) {
          indexRef.current -= 1;
        } else {
          // Already at oldest entry — do nothing.
          return;
        }

        setText(hist[indexRef.current]);
      } else if (e.key === "ArrowDown") {
        // Only intercept when on the last line.
        if (!isOnLastLine(el)) return;
        if (indexRef.current === -1) return; // Not navigating history.

        e.preventDefault();

        if (indexRef.current < hist.length - 1) {
          indexRef.current += 1;
          setText(hist[indexRef.current]);
        } else {
          // Past the newest entry — restore draft.
          indexRef.current = -1;
          setText(draftRef.current);
        }
      }
    },
    [setText],
  );

  return { handleHistoryKeyDown, addToHistory };
}
