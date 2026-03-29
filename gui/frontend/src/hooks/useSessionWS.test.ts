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
    this.onclose?.();
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
