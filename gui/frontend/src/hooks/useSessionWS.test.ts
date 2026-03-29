/**
 * Regression tests for useSessionWS — specifically the stream_complete
 * handler that must transition running/cancelling nodes to terminal state.
 *
 * Uses a minimal fake WebSocket to drive the hook through its lifecycle.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSessionWS } from "./useSessionWS";
import type { TreeData, TreeNode } from "@/api/types";

/* ---------- Fake WebSocket ---------- */

type WSHandler = (event: { data: string }) => void;

let fakeInstances: FakeWebSocket[] = [];

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readyState = FakeWebSocket.OPEN;
  onopen: (() => void) | null = null;
  onmessage: WSHandler | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];

  constructor(_url: string) {
    fakeInstances.push(this);
    // Simulate async open
    setTimeout(() => {
      this.readyState = FakeWebSocket.OPEN;
      this.onopen?.();
    }, 0);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.readyState = FakeWebSocket.CLOSED;
    // Fire onclose asynchronously to match real browser behavior — the
    // previous synchronous call masked the race condition where a stale
    // WebSocket's onclose handler could clobber a newer connection.
    const handler = this.onclose;
    if (handler) setTimeout(() => handler(), 0);
  }

  /** Test helper: simulate receiving a message from the server. */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  _receive(msg: any) {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
}

/* ---------- Helpers ---------- */

function makeNode(overrides: Partial<TreeNode> & { agent_id: string }): TreeNode {
  return {
    role: "worker",
    runtime: "claude",
    status: "running",
    exit_code: null,
    started_at: null,
    duration_ms: null,
    parent: null,
    current_activity: null,
    activity_action: null,
    ...overrides,
  };
}

function makeTreeData(nodes: TreeNode[]): TreeData & { type: string } {
  return {
    type: "tree_snapshot",
    nodes,
    pending_delegations: [],
    denied_delegations: [],
  };
}

/* ---------- Setup / Teardown ---------- */

beforeEach(() => {
  fakeInstances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/* ---------- Tests ---------- */

describe("useSessionWS stream_complete handling", () => {
  it("transitions running nodes to completed on stream_complete", async () => {
    const { result } = renderHook(() => useSessionWS("run-1", true));

    // Wait for WS connection
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    const ws = fakeInstances[0];
    expect(ws).toBeDefined();

    // Server sends tree snapshot with running nodes
    const tree = makeTreeData([
      makeNode({ agent_id: "root", role: "ceo", status: "running", current_activity: "thinking" }),
      makeNode({ agent_id: "child-1", role: "worker", status: "running", parent: "root" }),
      makeNode({ agent_id: "child-2", role: "reviewer", status: "completed", parent: "root" }),
    ]);

    act(() => ws._receive(tree));

    // Verify initial state — running nodes present
    expect(result.current.treeData).not.toBeNull();
    expect(result.current.treeData!.nodes.filter((n) => n.status === "running")).toHaveLength(2);

    // Server sends stream_complete
    act(() => ws._receive({ type: "stream_complete" }));

    // All previously-running nodes should now be completed
    const nodes = result.current.treeData!.nodes;
    expect(nodes.find((n) => n.agent_id === "root")!.status).toBe("completed");
    expect(nodes.find((n) => n.agent_id === "root")!.current_activity).toBeNull();
    expect(nodes.find((n) => n.agent_id === "child-1")!.status).toBe("completed");
    expect(nodes.find((n) => n.agent_id === "child-1")!.current_activity).toBeNull();
    // Already-completed node stays completed
    expect(nodes.find((n) => n.agent_id === "child-2")!.status).toBe("completed");

    // No running nodes remain
    expect(nodes.filter((n) => n.status === "running")).toHaveLength(0);
  });

  it("transitions cancelling nodes to cancelled on stream_complete", async () => {
    const { result } = renderHook(() => useSessionWS("run-2", true));

    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    const ws = fakeInstances[0];

    const tree = makeTreeData([
      makeNode({ agent_id: "root", role: "ceo", status: "cancelling" }),
      makeNode({ agent_id: "child-1", role: "worker", status: "running", parent: "root" }),
    ]);

    act(() => ws._receive(tree));
    act(() => ws._receive({ type: "stream_complete" }));

    const nodes = result.current.treeData!.nodes;
    expect(nodes.find((n) => n.agent_id === "root")!.status).toBe("cancelled");
    expect(nodes.find((n) => n.agent_id === "child-1")!.status).toBe("completed");
  });

  it("clears pending_delegations on stream_complete", async () => {
    const { result } = renderHook(() => useSessionWS("run-3", true));

    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    const ws = fakeInstances[0];

    const tree: TreeData & { type: string } = {
      type: "tree_snapshot",
      nodes: [makeNode({ agent_id: "root", role: "ceo", status: "running" })],
      pending_delegations: [
        { span_id: "span-1", role: "worker", requested_by: "root" } as never,
      ],
      denied_delegations: [],
    };

    act(() => ws._receive(tree));
    expect(result.current.treeData!.pending_delegations).toHaveLength(1);

    act(() => ws._receive({ type: "stream_complete" }));
    expect(result.current.treeData!.pending_delegations).toHaveLength(0);
  });

  it("leaves treeData unchanged if all nodes are already terminal", async () => {
    const { result } = renderHook(() => useSessionWS("run-4", true));

    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    const ws = fakeInstances[0];

    const tree = makeTreeData([
      makeNode({ agent_id: "root", role: "ceo", status: "completed" }),
      makeNode({ agent_id: "child-1", role: "worker", status: "failed", parent: "root" }),
    ]);

    act(() => ws._receive(tree));
    const before = result.current.treeData;

    act(() => ws._receive({ type: "stream_complete" }));
    // Same reference — no unnecessary re-render
    expect(result.current.treeData).toBe(before);
  });

  it("handles stream_complete when no treeData has been received", async () => {
    const { result } = renderHook(() => useSessionWS("run-5", true));

    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    const ws = fakeInstances[0];

    // stream_complete before any tree snapshot — should not crash
    act(() => ws._receive({ type: "stream_complete" }));
    expect(result.current.treeData).toBeNull();
    expect(result.current.connected).toBe(false);
  });
});

describe("useSessionWS cross-session isolation", () => {
  it("stale WebSocket onclose does not clobber new connection", async () => {
    const { result, rerender } = renderHook(
      ({ runId, active, scopeKey }: { runId: string; active: boolean; scopeKey: string }) =>
        useSessionWS(runId, active, scopeKey),
      { initialProps: { runId: "run-A", active: true, scopeKey: "conv-1" } },
    );

    // Wait for first WS connection
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    const wsOld = fakeInstances[0];
    expect(wsOld).toBeDefined();
    expect(result.current.connected).toBe(true);

    // Switch conversation — scopeKey changes, triggering effect cleanup + reconnect
    rerender({ runId: "run-A", active: true, scopeKey: "conv-2" });

    // Wait for new WS connection to open
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    const wsNew = fakeInstances[1];
    expect(wsNew).toBeDefined();
    expect(result.current.connected).toBe(true);

    // Old WebSocket's async onclose fires now (after the new connection is live)
    // Without the guard, this would null out wsRef and schedule a reconnect to the old URL
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    // The new connection should still be live — not clobbered by old onclose
    expect(result.current.connected).toBe(true);
    // Only 2 WebSocket instances should exist (no spurious reconnect from stale onclose)
    expect(fakeInstances).toHaveLength(2);
  });

  it("reconnects when scopeKey changes even with same runId", async () => {
    const { result, rerender } = renderHook(
      ({ runId, active, scopeKey }: { runId: string; active: boolean; scopeKey: string }) =>
        useSessionWS(runId, active, scopeKey),
      { initialProps: { runId: "run-X", active: true, scopeKey: "scope-1" } },
    );

    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    expect(fakeInstances).toHaveLength(1);
    expect(result.current.connected).toBe(true);

    // Change scopeKey only — should trigger a new WebSocket connection
    rerender({ runId: "run-X", active: true, scopeKey: "scope-2" });

    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    // A second WebSocket should have been created
    expect(fakeInstances).toHaveLength(2);
    expect(result.current.connected).toBe(true);
  });
});
