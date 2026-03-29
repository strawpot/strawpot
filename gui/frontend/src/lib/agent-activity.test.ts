import { describe, expect, it } from "vitest";
import {
  getAgentActivityLabel,
  getAgentActivityDetail,
  getSessionActivityLabel,
  getSessionActivityDetail,
} from "./agent-activity";
import type { TreeNode } from "@/api/types";

function makeNode(overrides: Partial<TreeNode> & { agent_id: string }): TreeNode {
  return {
    role: "test-role",
    runtime: "claude-code",
    status: "running",
    exit_code: null,
    started_at: null,
    duration_ms: null,
    parent: null,
    current_activity: null,
    ...overrides,
  };
}

// ---- getAgentActivityLabel (backward-compat) ----

describe("getAgentActivityLabel", () => {
  it("returns null for unknown agent", () => {
    expect(getAgentActivityLabel([], "nope")).toBeNull();
  });

  it("returns own current_activity when set", () => {
    const nodes = [makeNode({ agent_id: "root", current_activity: "Reading foo.ts" })];
    expect(getAgentActivityLabel(nodes, "root")).toBe("Reading foo.ts");
  });

  it("shows children aggregate even when parent has own activity", () => {
    const nodes = [
      makeNode({ agent_id: "root", current_activity: "Thinking" }),
      makeNode({ agent_id: "child", parent: "root", role: "cr", current_activity: "Reading bar.ts" }),
    ];
    // Children take priority over parent's own activity
    expect(getAgentActivityLabel(nodes, "root")).toBe("2 agents running");
  });

  it("shows count header for single running child (includes parent)", () => {
    const nodes = [
      makeNode({ agent_id: "root" }),
      makeNode({ agent_id: "child", parent: "root", role: "code-reviewer", current_activity: "Reading src/api.ts" }),
    ];
    expect(getAgentActivityLabel(nodes, "root")).toBe("2 agents running");
  });

  it("shows count header for single running child without activity (includes parent)", () => {
    const nodes = [
      makeNode({ agent_id: "root" }),
      makeNode({ agent_id: "child", parent: "root", role: "qa-engineer" }),
    ];
    expect(getAgentActivityLabel(nodes, "root")).toBe("2 agents running");
  });

  it("shows aggregate count for multiple running children (includes parent)", () => {
    const nodes = [
      makeNode({ agent_id: "root" }),
      makeNode({ agent_id: "c1", parent: "root", role: "code-reviewer" }),
      makeNode({ agent_id: "c2", parent: "root", role: "qa-engineer" }),
      makeNode({ agent_id: "c3", parent: "root", role: "comment-analyzer" }),
    ];
    expect(getAgentActivityLabel(nodes, "root")).toBe("4 agents running");
  });

  it("shows aggregate count without highlighted inline activity", () => {
    const nodes = [
      makeNode({ agent_id: "root" }),
      makeNode({ agent_id: "c1", parent: "root", role: "code-reviewer", current_activity: "Reading routes.ts" }),
      makeNode({ agent_id: "c2", parent: "root", role: "qa-engineer" }),
    ];
    // Header is just the count — activity is in childActivity, not header
    expect(getAgentActivityLabel(nodes, "root")).toBe("3 agents running");
  });

  it("ignores completed children", () => {
    const nodes = [
      makeNode({ agent_id: "root" }),
      makeNode({ agent_id: "c1", parent: "root", role: "code-reviewer", status: "completed" }),
      makeNode({ agent_id: "c2", parent: "root", role: "qa-engineer", current_activity: "Running tests" }),
    ];
    expect(getAgentActivityLabel(nodes, "root")).toBe("2 agents running");
  });

  it("returns null when no children and no own activity", () => {
    const nodes = [makeNode({ agent_id: "root" })];
    expect(getAgentActivityLabel(nodes, "root")).toBeNull();
  });

  it("does not aggregate grandchildren into parent count", () => {
    const nodes = [
      makeNode({ agent_id: "root" }),
      makeNode({ agent_id: "child", parent: "root", status: "completed" }),
      makeNode({ agent_id: "grandchild", parent: "child", role: "qa", current_activity: "Testing" }),
    ];
    expect(getAgentActivityLabel(nodes, "root")).toBeNull();
  });

  it("excludes cancelling and cancelled children from running count", () => {
    const nodes = [
      makeNode({ agent_id: "root" }),
      makeNode({ agent_id: "c1", parent: "root", role: "reviewer", status: "cancelling" }),
      makeNode({ agent_id: "c2", parent: "root", role: "qa", status: "cancelled" }),
    ];
    expect(getAgentActivityLabel(nodes, "root")).toBeNull();
  });
});

// ---- getAgentActivityDetail ----

describe("getAgentActivityDetail", () => {
  it("returns null for unknown agent", () => {
    expect(getAgentActivityDetail([], "nope")).toBeNull();
  });

  it("returns own activity with no child activity", () => {
    const nodes = [makeNode({ agent_id: "root", current_activity: "Reading foo.ts" })];
    const detail = getAgentActivityDetail(nodes, "root");
    expect(detail).toEqual({
      header: "Reading foo.ts",
      childActivity: null,
    });
  });

  it("shows children aggregate even when parent has own activity", () => {
    const nodes = [
      makeNode({ agent_id: "root", current_activity: "Thinking" }),
      makeNode({ agent_id: "child", parent: "root", role: "cr", current_activity: "Reading" }),
    ];
    const detail = getAgentActivityDetail(nodes, "root");
    // Running children take priority over parent's own activity
    expect(detail?.header).toBe("2 agents running");
    expect(detail?.childActivity).toBe("cr: Reading");
  });

  it("returns count header + most-recent child activity for one running child", () => {
    const nodes = [
      makeNode({ agent_id: "root" }),
      makeNode({ agent_id: "child", parent: "root", role: "code-reviewer", current_activity: "Reading src/api.ts" }),
    ];
    const detail = getAgentActivityDetail(nodes, "root");
    expect(detail?.header).toBe("2 agents running");
    expect(detail?.childActivity).toBe("code-reviewer: Reading src/api.ts");
  });

  it("returns role-prefixed Working… for child without activity", () => {
    const nodes = [
      makeNode({ agent_id: "root" }),
      makeNode({ agent_id: "child", parent: "root", role: "qa-engineer" }),
    ];
    const detail = getAgentActivityDetail(nodes, "root");
    expect(detail?.header).toBe("2 agents running");
    expect(detail?.childActivity).toBe("qa-engineer: Working…");
  });

  it("returns most-recent child activity for multiple running children", () => {
    const nodes = [
      makeNode({ agent_id: "root" }),
      makeNode({ agent_id: "c1", parent: "root", role: "code-reviewer", current_activity: "Reading routes.ts" }),
      makeNode({ agent_id: "c2", parent: "root", role: "qa-engineer" }),
      makeNode({ agent_id: "c3", parent: "root", role: "comment-analyzer", current_activity: "Analyzing PR" }),
    ];
    const detail = getAgentActivityDetail(nodes, "root");
    expect(detail?.header).toBe("4 agents running");
    expect(detail?.childActivity).toBe("comment-analyzer: Analyzing PR");
  });

  it("returns role-prefixed Working… when no children have activity", () => {
    const nodes = [
      makeNode({ agent_id: "root" }),
      makeNode({ agent_id: "c1", parent: "root", role: "code-reviewer" }),
      makeNode({ agent_id: "c2", parent: "root", role: "qa-engineer" }),
    ];
    const detail = getAgentActivityDetail(nodes, "root");
    expect(detail?.header).toBe("3 agents running");
    expect(detail?.childActivity).toBe("qa-engineer: Working…");
  });

  it("returns null when no children and no own activity", () => {
    expect(getAgentActivityDetail([makeNode({ agent_id: "root" })], "root")).toBeNull();
  });

  it("does not aggregate grandchildren into parent", () => {
    const nodes = [
      makeNode({ agent_id: "root" }),
      makeNode({ agent_id: "child", parent: "root", status: "completed" }),
      makeNode({ agent_id: "grandchild", parent: "child", role: "qa", current_activity: "Testing" }),
    ];
    expect(getAgentActivityDetail(nodes, "root")).toBeNull();
  });

  it("excludes cancelling and cancelled children", () => {
    const nodes = [
      makeNode({ agent_id: "root" }),
      makeNode({ agent_id: "c1", parent: "root", role: "reviewer", status: "cancelling" }),
      makeNode({ agent_id: "c2", parent: "root", role: "qa", status: "cancelled" }),
    ];
    expect(getAgentActivityDetail(nodes, "root")).toBeNull();
  });
});

// ---- getSessionActivityLabel (backward-compat) ----

describe("getSessionActivityLabel", () => {
  it("returns null for empty nodes", () => {
    expect(getSessionActivityLabel([])).toBeNull();
  });

  it("delegates to root node — shows count for single child (includes parent)", () => {
    const nodes = [
      makeNode({ agent_id: "root" }),
      makeNode({ agent_id: "c1", parent: "root", role: "reviewer", current_activity: "Reviewing" }),
    ];
    expect(getSessionActivityLabel(nodes)).toBe("2 agents running");
  });

  it("handles root with own activity", () => {
    const nodes = [
      makeNode({ agent_id: "root", role: "implementer", current_activity: "Writing code" }),
    ];
    expect(getSessionActivityLabel(nodes)).toBe("Writing code");
  });

  it("handles root with multiple children (includes parent)", () => {
    const nodes = [
      makeNode({ agent_id: "root" }),
      makeNode({ agent_id: "c1", parent: "root", role: "cr" }),
      makeNode({ agent_id: "c2", parent: "root", role: "qa" }),
    ];
    expect(getSessionActivityLabel(nodes)).toBe("3 agents running");
  });

  it("falls back when root is completed but children still running", () => {
    const nodes = [
      makeNode({ agent_id: "root", status: "completed" }),
      makeNode({ agent_id: "c1", parent: "root", role: "reviewer", current_activity: "Reading" }),
    ];
    expect(getSessionActivityLabel(nodes)).toBe("1 agent running");
  });

  it("aggregates multiple running roots", () => {
    const nodes = [
      makeNode({ agent_id: "root1" }),
      makeNode({ agent_id: "root2" }),
    ];
    expect(getSessionActivityLabel(nodes)).toBe("2 agents running");
  });

  it("uses singular 'agent' for one non-root running node in flat fallback", () => {
    const nodes = [
      makeNode({ agent_id: "root", status: "completed" }),
      makeNode({ agent_id: "c1", parent: "root", role: "qa" }),
    ];
    expect(getSessionActivityLabel(nodes)).toBe("1 agent running");
  });

  it("uses plural 'agents' for multiple non-root running nodes in flat fallback", () => {
    const nodes = [
      makeNode({ agent_id: "root", status: "completed" }),
      makeNode({ agent_id: "c1", parent: "root", role: "qa" }),
      makeNode({ agent_id: "c2", parent: "root", role: "cr" }),
    ];
    expect(getSessionActivityLabel(nodes)).toBe("2 agents running");
  });

  it("returns null when all nodes are terminal", () => {
    const nodes = [
      makeNode({ agent_id: "root", status: "completed" }),
      makeNode({ agent_id: "c1", parent: "root", status: "completed" }),
    ];
    expect(getSessionActivityLabel(nodes)).toBeNull();
  });
});

// ---- getSessionActivityDetail ----

describe("getSessionActivityDetail", () => {
  it("returns null for empty nodes", () => {
    expect(getSessionActivityDetail([])).toBeNull();
  });

  it("returns most-recent child activity for root with children (includes parent)", () => {
    const nodes = [
      makeNode({ agent_id: "root" }),
      makeNode({ agent_id: "c1", parent: "root", role: "code-reviewer", current_activity: "Reviewing" }),
      makeNode({ agent_id: "c2", parent: "root", role: "qa-engineer", current_activity: "Testing" }),
    ];
    const detail = getSessionActivityDetail(nodes);
    expect(detail?.header).toBe("3 agents running");
    expect(detail?.childActivity).toBe("qa-engineer: Testing");
  });

  it("returns no child activity for root with own activity", () => {
    const nodes = [
      makeNode({ agent_id: "root", current_activity: "Writing code" }),
    ];
    const detail = getSessionActivityDetail(nodes);
    expect(detail).toEqual({ header: "Writing code", childActivity: null });
  });

  it("returns no child activity for multiple running roots", () => {
    const nodes = [
      makeNode({ agent_id: "root1" }),
      makeNode({ agent_id: "root2" }),
    ];
    const detail = getSessionActivityDetail(nodes);
    expect(detail).toEqual({ header: "2 agents running", childActivity: null });
  });

  it("returns most-recent child activity in flat fallback", () => {
    const nodes = [
      makeNode({ agent_id: "root", status: "completed" }),
      makeNode({ agent_id: "c1", parent: "root", role: "qa", current_activity: "Testing" }),
      makeNode({ agent_id: "c2", parent: "root", role: "cr" }),
    ];
    const detail = getSessionActivityDetail(nodes);
    expect(detail?.header).toBe("2 agents running");
    expect(detail?.childActivity).toBe("qa: Testing");
  });

  it("returns role-prefixed Working… when flat fallback has no activity", () => {
    const nodes = [
      makeNode({ agent_id: "root", status: "completed" }),
      makeNode({ agent_id: "c1", parent: "root", role: "qa" }),
    ];
    const detail = getSessionActivityDetail(nodes);
    expect(detail?.header).toBe("1 agent running");
    expect(detail?.childActivity).toBe("qa: Working…");
  });

  it("returns null when all nodes are terminal", () => {
    const nodes = [
      makeNode({ agent_id: "root", status: "completed" }),
      makeNode({ agent_id: "c1", parent: "root", status: "completed" }),
    ];
    expect(getSessionActivityDetail(nodes)).toBeNull();
  });
});
