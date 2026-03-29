import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { usePromptHistory } from "./usePromptHistory";
import type React from "react";

/* ---------- Helpers ---------- */

/** Build a minimal fake KeyboardEvent targeting a fake textarea. */
function makeKeyEvent(
  key: string,
  textareaOverrides: {
    value?: string;
    selectionStart?: number;
    selectionEnd?: number;
  } = {},
): React.KeyboardEvent<HTMLTextAreaElement> {
  const defaultValue = textareaOverrides.value ?? "";
  const el = {
    value: defaultValue,
    selectionStart: textareaOverrides.selectionStart ?? 0,
    selectionEnd: textareaOverrides.selectionEnd ?? 0,
  } as HTMLTextAreaElement;

  return {
    key,
    currentTarget: el,
    preventDefault: vi.fn(),
  } as unknown as React.KeyboardEvent<HTMLTextAreaElement>;
}

/* ---------- Tests ---------- */

describe("usePromptHistory", () => {
  let text: string;
  const setText = vi.fn<(v: string) => void>();

  beforeEach(() => {
    text = "";
    setText.mockClear();
    setText.mockImplementation((v: string) => {
      text = v;
    });
  });

  function renderHistory() {
    return renderHook(
      (props: { text: string }) =>
        usePromptHistory({ text: props.text, setText }),
      { initialProps: { text } },
    );
  }

  describe("addToHistory", () => {
    it("stores submitted prompts", () => {
      const { result } = renderHistory();

      act(() => result.current.addToHistory("hello"));
      act(() => result.current.addToHistory("world"));

      // Navigate up twice to verify both entries exist.
      const e1 = makeKeyEvent("ArrowUp", { value: "", selectionStart: 0 });
      act(() => result.current.handleHistoryKeyDown(e1));
      expect(setText).toHaveBeenLastCalledWith("world");

      const e2 = makeKeyEvent("ArrowUp", { value: "world", selectionStart: 0 });
      act(() => result.current.handleHistoryKeyDown(e2));
      expect(setText).toHaveBeenLastCalledWith("hello");
    });

    it("ignores empty/whitespace prompts", () => {
      const { result } = renderHistory();

      act(() => result.current.addToHistory(""));
      act(() => result.current.addToHistory("   "));

      // ArrowUp should do nothing — no history.
      const e = makeKeyEvent("ArrowUp", { value: "", selectionStart: 0 });
      act(() => result.current.handleHistoryKeyDown(e));
      expect(e.preventDefault).not.toHaveBeenCalled();
    });

    it("deduplicates consecutive identical prompts", () => {
      const { result } = renderHistory();

      act(() => result.current.addToHistory("same"));
      act(() => result.current.addToHistory("same"));
      act(() => result.current.addToHistory("same"));

      // One ArrowUp → "same", second ArrowUp should not move further.
      const e1 = makeKeyEvent("ArrowUp", { value: "", selectionStart: 0 });
      act(() => result.current.handleHistoryKeyDown(e1));
      expect(setText).toHaveBeenLastCalledWith("same");

      // Already at oldest — should not call setText again.
      setText.mockClear();
      const e2 = makeKeyEvent("ArrowUp", { value: "same", selectionStart: 0 });
      act(() => result.current.handleHistoryKeyDown(e2));
      expect(setText).not.toHaveBeenCalled();
    });
  });

  describe("ArrowUp navigation", () => {
    it("does nothing when history is empty", () => {
      const { result } = renderHistory();
      const e = makeKeyEvent("ArrowUp", { value: "", selectionStart: 0 });

      act(() => result.current.handleHistoryKeyDown(e));

      expect(e.preventDefault).not.toHaveBeenCalled();
      expect(setText).not.toHaveBeenCalled();
    });

    it("recalls the most recent prompt on first ArrowUp", () => {
      const { result } = renderHistory();
      act(() => result.current.addToHistory("first"));
      act(() => result.current.addToHistory("second"));

      const e = makeKeyEvent("ArrowUp", { value: "", selectionStart: 0 });
      act(() => result.current.handleHistoryKeyDown(e));

      expect(e.preventDefault).toHaveBeenCalled();
      expect(setText).toHaveBeenCalledWith("second");
    });

    it("navigates to older entries on successive ArrowUp", () => {
      const { result } = renderHistory();
      act(() => result.current.addToHistory("a"));
      act(() => result.current.addToHistory("b"));
      act(() => result.current.addToHistory("c"));

      // First up → "c"
      act(() =>
        result.current.handleHistoryKeyDown(
          makeKeyEvent("ArrowUp", { value: "", selectionStart: 0 }),
        ),
      );
      expect(setText).toHaveBeenLastCalledWith("c");

      // Second up → "b"
      act(() =>
        result.current.handleHistoryKeyDown(
          makeKeyEvent("ArrowUp", { value: "c", selectionStart: 0 }),
        ),
      );
      expect(setText).toHaveBeenLastCalledWith("b");

      // Third up → "a"
      act(() =>
        result.current.handleHistoryKeyDown(
          makeKeyEvent("ArrowUp", { value: "b", selectionStart: 0 }),
        ),
      );
      expect(setText).toHaveBeenLastCalledWith("a");
    });

    it("stops at the oldest entry", () => {
      const { result } = renderHistory();
      act(() => result.current.addToHistory("only"));

      act(() =>
        result.current.handleHistoryKeyDown(
          makeKeyEvent("ArrowUp", { value: "", selectionStart: 0 }),
        ),
      );
      expect(setText).toHaveBeenLastCalledWith("only");

      // Another ArrowUp should not call setText again.
      setText.mockClear();
      act(() =>
        result.current.handleHistoryKeyDown(
          makeKeyEvent("ArrowUp", { value: "only", selectionStart: 0 }),
        ),
      );
      expect(setText).not.toHaveBeenCalled();
    });

    it("does NOT intercept when cursor is NOT on the first line", () => {
      const { result } = renderHistory();
      act(() => result.current.addToHistory("prev"));

      // Cursor is on line 2 of a multiline value.
      const e = makeKeyEvent("ArrowUp", {
        value: "line1\nline2",
        selectionStart: 8, // middle of "line2"
      });
      act(() => result.current.handleHistoryKeyDown(e));

      expect(e.preventDefault).not.toHaveBeenCalled();
      expect(setText).not.toHaveBeenCalled();
    });

    it("intercepts when cursor is on the first line of multiline text", () => {
      const { result } = renderHistory();
      act(() => result.current.addToHistory("prev"));

      // Cursor at position 3 — within "line1" (before the \n at index 5).
      const e = makeKeyEvent("ArrowUp", {
        value: "line1\nline2",
        selectionStart: 3,
      });
      act(() => result.current.handleHistoryKeyDown(e));

      expect(e.preventDefault).toHaveBeenCalled();
      expect(setText).toHaveBeenCalledWith("prev");
    });
  });

  describe("ArrowDown navigation", () => {
    it("does nothing when not navigating history", () => {
      const { result } = renderHistory();
      act(() => result.current.addToHistory("something"));

      const e = makeKeyEvent("ArrowDown", { value: "", selectionStart: 0 });
      act(() => result.current.handleHistoryKeyDown(e));

      expect(e.preventDefault).not.toHaveBeenCalled();
      expect(setText).not.toHaveBeenCalled();
    });

    it("navigates forward and restores draft", () => {
      text = "my draft";
      const { result, rerender } = renderHistory();

      act(() => result.current.addToHistory("old"));
      act(() => result.current.addToHistory("new"));

      // Rerender with current text so the hook sees the draft.
      rerender({ text: "my draft" });

      // Up → "new" (stashes "my draft")
      act(() =>
        result.current.handleHistoryKeyDown(
          makeKeyEvent("ArrowUp", { value: "my draft", selectionStart: 0 }),
        ),
      );
      expect(setText).toHaveBeenLastCalledWith("new");

      // Up → "old"
      act(() =>
        result.current.handleHistoryKeyDown(
          makeKeyEvent("ArrowUp", { value: "new", selectionStart: 0 }),
        ),
      );
      expect(setText).toHaveBeenLastCalledWith("old");

      // Down → "new"
      act(() =>
        result.current.handleHistoryKeyDown(
          makeKeyEvent("ArrowDown", {
            value: "old",
            selectionStart: 3,
          }),
        ),
      );
      expect(setText).toHaveBeenLastCalledWith("new");

      // Down → restore draft "my draft"
      act(() =>
        result.current.handleHistoryKeyDown(
          makeKeyEvent("ArrowDown", {
            value: "new",
            selectionStart: 3,
          }),
        ),
      );
      expect(setText).toHaveBeenLastCalledWith("my draft");
    });

    it("does NOT intercept when cursor is NOT on the last line", () => {
      const { result } = renderHistory();
      act(() => result.current.addToHistory("prev"));

      // Navigate into history first.
      act(() =>
        result.current.handleHistoryKeyDown(
          makeKeyEvent("ArrowUp", { value: "", selectionStart: 0 }),
        ),
      );

      // Cursor on first line of multiline — not on last line.
      const e = makeKeyEvent("ArrowDown", {
        value: "line1\nline2",
        selectionStart: 3,
      });
      act(() => result.current.handleHistoryKeyDown(e));

      expect(e.preventDefault).not.toHaveBeenCalled();
    });

    it("intercepts when cursor is on the last line of multiline text", () => {
      const { result } = renderHistory();
      act(() => result.current.addToHistory("old"));
      act(() => result.current.addToHistory("new"));

      // Navigate into history first.
      act(() =>
        result.current.handleHistoryKeyDown(
          makeKeyEvent("ArrowUp", { value: "", selectionStart: 0 }),
        ),
      );
      expect(setText).toHaveBeenLastCalledWith("new");

      // Cursor on last line of multiline — should intercept.
      const e = makeKeyEvent("ArrowDown", {
        value: "line1\nline2",
        selectionStart: 8, // middle of "line2"
      });
      act(() => result.current.handleHistoryKeyDown(e));

      expect(e.preventDefault).toHaveBeenCalled();
    });
  });

  describe("boundary edge cases", () => {
    it("ArrowUp intercepts when cursor is exactly at the newline position", () => {
      const { result } = renderHistory();
      act(() => result.current.addToHistory("prev"));

      // selectionStart === index of \n (position 5 in "line1\nline2")
      const e = makeKeyEvent("ArrowUp", {
        value: "line1\nline2",
        selectionStart: 5, // exactly at the \n
      });
      act(() => result.current.handleHistoryKeyDown(e));

      // isOnFirstLine returns true when pos <= firstNewline, so pos=5 is first line.
      expect(e.preventDefault).toHaveBeenCalled();
      expect(setText).toHaveBeenCalledWith("prev");
    });

    it("ArrowDown does NOT intercept when cursor is exactly at the last newline", () => {
      const { result } = renderHistory();
      act(() => result.current.addToHistory("prev"));

      // Navigate into history first.
      act(() =>
        result.current.handleHistoryKeyDown(
          makeKeyEvent("ArrowUp", { value: "", selectionStart: 0 }),
        ),
      );

      // selectionStart === index of last \n (position 5 in "line1\nline2").
      // isOnLastLine uses pos > lastNewline (strict), so pos=5 is NOT last line.
      const e = makeKeyEvent("ArrowDown", {
        value: "line1\nline2",
        selectionStart: 5, // exactly at the \n
      });
      act(() => result.current.handleHistoryKeyDown(e));

      expect(e.preventDefault).not.toHaveBeenCalled();
    });

    it("preserves non-consecutive duplicate entries", () => {
      const { result } = renderHistory();
      act(() => result.current.addToHistory("a"));
      act(() => result.current.addToHistory("b"));
      act(() => result.current.addToHistory("a")); // not consecutive dup of "a"

      // Up → "a" (most recent)
      act(() =>
        result.current.handleHistoryKeyDown(
          makeKeyEvent("ArrowUp", { value: "", selectionStart: 0 }),
        ),
      );
      expect(setText).toHaveBeenLastCalledWith("a");

      // Up → "b"
      act(() =>
        result.current.handleHistoryKeyDown(
          makeKeyEvent("ArrowUp", { value: "a", selectionStart: 0 }),
        ),
      );
      expect(setText).toHaveBeenLastCalledWith("b");

      // Up → "a" (oldest)
      act(() =>
        result.current.handleHistoryKeyDown(
          makeKeyEvent("ArrowUp", { value: "b", selectionStart: 0 }),
        ),
      );
      expect(setText).toHaveBeenLastCalledWith("a");
    });
  });

  describe("history reset on new submission", () => {
    it("resets navigation index after addToHistory", () => {
      const { result } = renderHistory();
      act(() => result.current.addToHistory("first"));

      // Navigate up.
      act(() =>
        result.current.handleHistoryKeyDown(
          makeKeyEvent("ArrowUp", { value: "", selectionStart: 0 }),
        ),
      );
      expect(setText).toHaveBeenLastCalledWith("first");

      // Submit a new prompt — resets navigation.
      act(() => result.current.addToHistory("second"));

      // ArrowDown should do nothing (not in history navigation).
      setText.mockClear();
      act(() =>
        result.current.handleHistoryKeyDown(
          makeKeyEvent("ArrowDown", { value: "second", selectionStart: 6 }),
        ),
      );
      expect(setText).not.toHaveBeenCalled();

      // ArrowUp should go to "second" (the newest).
      act(() =>
        result.current.handleHistoryKeyDown(
          makeKeyEvent("ArrowUp", { value: "", selectionStart: 0 }),
        ),
      );
      expect(setText).toHaveBeenLastCalledWith("second");
    });
  });
});
