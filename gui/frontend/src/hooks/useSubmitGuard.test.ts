import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useSubmitGuard } from "./useSubmitGuard";

describe("useSubmitGuard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("allows the first submit", () => {
    const { result } = renderHook(() => useSubmitGuard());
    expect(result.current.trySubmit("hello", false)).toBe(true);
  });

  it("blocks when isPending is true", () => {
    const { result } = renderHook(() => useSubmitGuard());
    expect(result.current.trySubmit("hello", true)).toBe(false);
  });

  it("blocks a second submit within 300ms (debounce)", () => {
    const { result } = renderHook(() => useSubmitGuard());

    act(() => {
      expect(result.current.trySubmit("hello", false)).toBe(true);
    });

    // Advance only 100ms — still within debounce window
    vi.advanceTimersByTime(100);

    act(() => {
      expect(result.current.trySubmit("different message", false)).toBe(false);
    });
  });

  it("allows submit after debounce window passes", () => {
    const { result } = renderHook(() => useSubmitGuard());

    act(() => {
      expect(result.current.trySubmit("hello", false)).toBe(true);
    });

    vi.advanceTimersByTime(300);

    act(() => {
      expect(result.current.trySubmit("hello again", false)).toBe(true);
    });
  });

  it("blocks duplicate message even at debounce boundary", () => {
    const { result } = renderHook(() => useSubmitGuard());

    act(() => {
      expect(result.current.trySubmit("same message", false)).toBe(true);
    });

    // Advance exactly 300ms — debounce passes but duplicate window (600ms) still active
    vi.advanceTimersByTime(300);

    act(() => {
      expect(result.current.trySubmit("same message", false)).toBe(false);
    });
  });

  it("allows same message after duplicate window (600ms)", () => {
    const { result } = renderHook(() => useSubmitGuard());

    act(() => {
      expect(result.current.trySubmit("same message", false)).toBe(true);
    });

    vi.advanceTimersByTime(600);

    act(() => {
      expect(result.current.trySubmit("same message", false)).toBe(true);
    });
  });

  it("allows different message after debounce even within duplicate window", () => {
    const { result } = renderHook(() => useSubmitGuard());

    act(() => {
      expect(result.current.trySubmit("first", false)).toBe(true);
    });

    vi.advanceTimersByTime(300);

    act(() => {
      expect(result.current.trySubmit("second", false)).toBe(true);
    });
  });

  it("blocks rapid double-submit (the actual bug scenario: 0.5-0.7ms apart)", () => {
    const { result } = renderHook(() => useSubmitGuard());

    act(() => {
      expect(result.current.trySubmit("build the feature", false)).toBe(true);
    });

    // Simulate near-simultaneous second call (< 1ms later)
    vi.advanceTimersByTime(1);

    act(() => {
      expect(result.current.trySubmit("build the feature", false)).toBe(false);
    });
  });

  it("blocks at 299ms (debounce boundary off-by-one)", () => {
    const { result } = renderHook(() => useSubmitGuard());

    act(() => {
      expect(result.current.trySubmit("hello", false)).toBe(true);
    });

    vi.advanceTimersByTime(299);

    act(() => {
      expect(result.current.trySubmit("world", false)).toBe(false);
    });
  });

  it("tracks state correctly across a 3-submit sequence", () => {
    const { result } = renderHook(() => useSubmitGuard());

    // Submit A at t=0
    act(() => {
      expect(result.current.trySubmit("A", false)).toBe(true);
    });

    // Submit B at t=300 — allowed (debounce passed, different message)
    vi.advanceTimersByTime(300);
    act(() => {
      expect(result.current.trySubmit("B", false)).toBe(true);
    });

    // Submit B at t=350 — blocked by debounce (only 50ms since last accepted)
    vi.advanceTimersByTime(50);
    act(() => {
      expect(result.current.trySubmit("B", false)).toBe(false);
    });
  });
});
