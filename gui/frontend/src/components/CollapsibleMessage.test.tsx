import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CollapsibleMessage from "./CollapsibleMessage";

// --------------------------------------------------------------------------
// Helpers
// --------------------------------------------------------------------------

/** Stub ResizeObserver — jsdom doesn't implement it. */
class MockResizeObserver {
  callback: ResizeObserverCallback;
  static instances: MockResizeObserver[] = [];

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
    MockResizeObserver.instances.push(this);
  }
  observe() {}
  unobserve() {}
  disconnect() {}

  /** Simulate a content resize by firing the observer callback. */
  static fireAll() {
    for (const instance of MockResizeObserver.instances) {
      instance.callback([] as unknown as ResizeObserverEntry[], instance as unknown as ResizeObserver);
    }
  }
}

let scrollHeightSpy: ReturnType<typeof vi.spyOn> | null = null;

beforeEach(() => {
  MockResizeObserver.instances = [];
  vi.stubGlobal("ResizeObserver", MockResizeObserver);
});

afterEach(() => {
  scrollHeightSpy?.mockRestore();
  scrollHeightSpy = null;
});

/**
 * Mock scrollHeight on the content div so the component thinks it measured
 * a certain pixel height. jsdom doesn't layout, so scrollHeight is always 0
 * unless we override it.
 */
function mockContentHeight(height: number) {
  scrollHeightSpy?.mockRestore();
  scrollHeightSpy = vi.spyOn(HTMLDivElement.prototype, "scrollHeight", "get").mockReturnValue(height);
}

/** Query the content wrapper by data-testid. */
function getContentEl(container: HTMLElement) {
  return container.querySelector('[data-testid="collapsible-content"]') as HTMLElement;
}

/** Query the gradient overlay by data-testid. */
function getGradientEl(container: HTMLElement) {
  return container.querySelector('[data-testid="gradient-overlay"]') as HTMLElement | null;
}

// --------------------------------------------------------------------------
// Tests
// --------------------------------------------------------------------------

describe("CollapsibleMessage", () => {
  // ---- Short content: no collapse UI ----

  it("renders children without collapse controls when content is short", () => {
    mockContentHeight(200); // well below 500px threshold

    const { container } = render(
      <CollapsibleMessage>
        <p>Short message</p>
      </CollapsibleMessage>,
    );

    expect(screen.getByText("Short message")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    // No max-height constraint on short content
    expect(getContentEl(container).style.maxHeight).toBe("");
  });

  // ---- Long content: collapse UI shown ----

  it("shows toggle button and constrains height when content exceeds threshold", () => {
    mockContentHeight(600);

    const { container } = render(
      <CollapsibleMessage>
        <p>Very long message</p>
      </CollapsibleMessage>,
    );

    const btn = screen.getByRole("button");
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveTextContent(/show more/i);

    // Collapsed preview height is 160px
    expect(getContentEl(container).style.maxHeight).toBe("160px");
  });

  it("renders gradient overlay when collapsed", () => {
    mockContentHeight(600);

    const { container } = render(
      <CollapsibleMessage gradientColor="rgb(255, 0, 0)">
        <p>Content</p>
      </CollapsibleMessage>,
    );

    const gradient = getGradientEl(container);
    expect(gradient).toBeTruthy();
    expect(gradient!.style.background).toContain("rgb(255, 0, 0)");
  });

  it("displays approximate extra-lines count", () => {
    // contentHeight=800, preview=160 → (800-160)/20 = 32 lines
    mockContentHeight(800);

    render(
      <CollapsibleMessage>
        <p>Content</p>
      </CollapsibleMessage>,
    );

    expect(screen.getByText(/~32 more lines/)).toBeInTheDocument();
  });

  // ---- Toggle expand / collapse ----

  it("expands content when 'Show more' is clicked", async () => {
    const user = userEvent.setup();
    mockContentHeight(600);

    const { container } = render(
      <CollapsibleMessage>
        <p>Content</p>
      </CollapsibleMessage>,
    );

    await user.click(screen.getByRole("button"));

    // Expanded: maxHeight equals measured contentHeight
    expect(getContentEl(container).style.maxHeight).toBe("600px");
    expect(screen.getByRole("button")).toHaveTextContent(/show less/i);
  });

  it("collapses back when 'Show less' is clicked", async () => {
    const user = userEvent.setup();
    mockContentHeight(600);

    const { container } = render(
      <CollapsibleMessage>
        <p>Content</p>
      </CollapsibleMessage>,
    );

    // Expand then collapse
    await user.click(screen.getByRole("button"));
    await user.click(screen.getByRole("button"));

    expect(getContentEl(container).style.maxHeight).toBe("160px");
    expect(screen.getByRole("button")).toHaveTextContent(/show more/i);
  });

  it("removes gradient overlay when expanded", async () => {
    const user = userEvent.setup();
    mockContentHeight(600);

    const { container } = render(
      <CollapsibleMessage>
        <p>Content</p>
      </CollapsibleMessage>,
    );

    await user.click(screen.getByRole("button"));

    expect(getGradientEl(container)).toBeNull();
  });

  // ---- Keyboard accessibility ----

  it("toggle button has correct aria-expanded reflecting visible state", async () => {
    const user = userEvent.setup();
    mockContentHeight(600);

    render(
      <CollapsibleMessage>
        <p>Content</p>
      </CollapsibleMessage>,
    );

    const btn = screen.getByRole("button");
    // Content is truncated (not fully visible) → aria-expanded is false
    expect(btn).toHaveAttribute("aria-expanded", "false");

    await user.click(btn);
    // Content is fully visible → aria-expanded is true
    expect(btn).toHaveAttribute("aria-expanded", "true");
  });

  it("toggle is activatable via keyboard Enter", async () => {
    const user = userEvent.setup();
    mockContentHeight(600);

    render(
      <CollapsibleMessage>
        <p>Content</p>
      </CollapsibleMessage>,
    );

    const btn = screen.getByRole("button");
    btn.focus();
    await user.keyboard("{Enter}");

    expect(btn).toHaveTextContent(/show less/i);
  });

  // ---- Boundary / edge cases ----

  it("does not collapse content exactly at threshold (500px)", () => {
    mockContentHeight(500);

    render(
      <CollapsibleMessage>
        <p>Content</p>
      </CollapsibleMessage>,
    );

    // 500 is NOT > 500, so no collapse
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("collapses content just above threshold (501px)", () => {
    mockContentHeight(501);

    render(
      <CollapsibleMessage>
        <p>Content</p>
      </CollapsibleMessage>,
    );

    expect(screen.getByRole("button")).toBeInTheDocument();
  });

  it("does not collapse when content has no measurable height", () => {
    mockContentHeight(0);

    const { container } = render(
      <CollapsibleMessage>{null}</CollapsibleMessage>,
    );

    expect(container).toBeTruthy();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  // ---- gradientColor prop ----

  it("uses default gradient color when prop is omitted", () => {
    mockContentHeight(600);

    const { container } = render(
      <CollapsibleMessage>
        <p>Content</p>
      </CollapsibleMessage>,
    );

    const gradient = getGradientEl(container);
    expect(gradient!.style.background).toContain("var(--color-muted)");
  });

  // ---- Scroll preservation on collapse ----

  it("calls scrollIntoView only when collapsing, not when expanding", async () => {
    const user = userEvent.setup();
    mockContentHeight(600);

    const scrollIntoViewMock = vi.fn();
    HTMLDivElement.prototype.scrollIntoView = scrollIntoViewMock;

    render(
      <CollapsibleMessage>
        <p>Content</p>
      </CollapsibleMessage>,
    );

    // Expand — should NOT call scrollIntoView
    await user.click(screen.getByRole("button"));
    expect(scrollIntoViewMock).not.toHaveBeenCalled();

    // Collapse — should trigger scrollIntoView via rAF
    await user.click(screen.getByRole("button"));
    await vi.waitFor(() => {
      expect(scrollIntoViewMock).toHaveBeenCalled();
    });
  });

  // ---- ResizeObserver dynamic content ----

  it("re-evaluates collapse state when ResizeObserver fires a resize", () => {
    // Start below threshold — no collapse
    mockContentHeight(200);

    const { container } = render(
      <CollapsibleMessage>
        <p>Dynamic content</p>
      </CollapsibleMessage>,
    );

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(getContentEl(container).style.maxHeight).toBe("");

    // Simulate content growing (e.g. lazy image loaded) above threshold
    mockContentHeight(700);
    act(() => {
      MockResizeObserver.fireAll();
    });

    // Now collapse UI should appear
    expect(screen.getByRole("button")).toBeInTheDocument();
    expect(getContentEl(container).style.maxHeight).toBe("160px");
  });

  it("removes collapse UI when content shrinks below threshold", () => {
    // Start above threshold
    mockContentHeight(600);

    render(
      <CollapsibleMessage>
        <p>Content</p>
      </CollapsibleMessage>,
    );

    expect(screen.getByRole("button")).toBeInTheDocument();

    // Simulate content shrinking below threshold
    mockContentHeight(300);
    act(() => {
      MockResizeObserver.fireAll();
    });

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  // ---- className pass-through ----

  it("applies custom className to wrapper", () => {
    mockContentHeight(200);

    const { container } = render(
      <CollapsibleMessage className="my-custom-class">
        <p>Content</p>
      </CollapsibleMessage>,
    );

    expect(container.firstElementChild).toHaveClass("my-custom-class");
  });
});
