import { describe, expect, it } from "vitest";
import { getAgentActivityLabel, getSessionActivityLabel } from "./agent-activity";
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

describe("getAgentActivityLabel", () => {
  it("returns null for unknown agent", () => {
    expect(getAgentActivityLabel([], "nope")).toBeNull();
  });

  it("returns own current_activity when set", () => {
    const nodes = [makeNode({ agent_id: "root", current_activity: "Reading foo.ts" })];
    expect(getAgentActivityLabel(nodes, "root")).toBe("Reading foo.ts");
  });

  it("prefers own activity over children activity", () => {
    const nodes = [
      makeNode({ agent_id: "root", current_activity: "Thinking" }),
      makeNode({ agent_id: "child", parent: "root", current_activity: "Reading bar.ts" }),
    ];
    expect(getAgentActivityLabel(nodes, "root")).toBe("Thinking");
  });

  it("shows single running child with activity", () => {
    const nodes = [
      makeNode({ agent_id: "root" }),
      makeNode({ agent_id: "child", parent: "root", role: "code-reviewer", current_activity: "Reading src/api.ts" }),
    ];
    expect(getAgentActivityLabel(nodes, "root")).toBe("code-reviewer: Reading src/api.ts");
  });

  it("shows single running child without activity", () => {
    const nodes = [
      makeNode({ agent_id: "root" }),
      makeNode({ agent_id: "child", parent: "root", role: "qa-engineer" }),
    ];
    expect(getAgentActivityLabel(nodes, "root")).toBe("qa-engineer running");
  });

  it("shows aggregate count for multiple running children", () => {
    const nodes = [
      makeNode({ agent_id: "root" }),
      makeNode({ agent_id: "c1", parent: "root", role: "code-reviewer" }),
      makeNode({ agent_id: "c2", parent: "root", role: "qa-engineer" }),
      makeNode({ agent_id: "c3", parent: "root", role: "comment-analyzer" }),
    ];
    expect(getAgentActivityLabel(nodes, "root")).toBe("3 agents running");
  });

  it("shows aggregate count with highlighted activity", () => {
    const nodes = [
      makeNode({ agent_id: "root" }),
      makeNode({ agent_id: "c1", parent: "root", role: "code-reviewer", current_activity: "Reading routes.ts" }),
      makeNode({ agent_id: "c2", parent: "root", role: "qa-engineer" }),
    ];
    expect(getAgentActivityLabel(nodes, "root")).toBe(
      "2 agents running · code-reviewer: Reading routes.ts",
    );
  });

  it("ignores completed children", () => {
    const nodes = [
      makeNode({ agent_id: "root" }),
      makeNode({ agent_id: "c1", parent: "root", role: "code-reviewer", status: "completed" }),
      makeNode({ agent_id: "c2", parent: "root", role: "qa-engineer", current_activity: "Running tests" }),
    ];
    expect(getAgentActivityLabel(nodes, "root")).toBe("qa-engineer: Running tests");
  });

  it("returns null when no children and no own activity", () => {
    const nodes = [makeNode({ agent_id: "root" })];
    expect(getAgentActivityLabel(nodes, "root")).toBeNull();
  });
});

describe("getSessionActivityLabel", () => {
  it("returns null for empty nodes", () => {
    expect(getSessionActivityLabel([])).toBeNull();
  });

  it("delegates to root node", () => {
    const nodes = [
      makeNode({ agent_id: "root" }),
      makeNode({ agent_id: "c1", parent: "root", role: "reviewer", current_activity: "Reviewing" }),
    ];
    expect(getSessionActivityLabel(nodes)).toBe("reviewer: Reviewing");
  });

  it("handles root with own activity", () => {
    const nodes = [
      makeNode({ agent_id: "root", role: "implementer", current_activity: "Writing code" }),
    ];
    expect(getSessionActivityLabel(nodes)).toBe("Writing code");
  });

  it("handles root with multiple children", () => {
    const nodes = [
      makeNode({ agent_id: "root" }),
      makeNode({ agent_id: "c1", parent: "root", role: "cr" }),
      makeNode({ agent_id: "c2", parent: "root", role: "qa" }),
    ];
    expect(getSessionActivityLabel(nodes)).toBe("2 agents running");
  });

  it("falls back when root is completed but children still running", () => {
    const nodes = [
      makeNode({ agent_id: "root", status: "completed" }),
      makeNode({ agent_id: "c1", parent: "root", role: "reviewer", current_activity: "Reading" }),
    ];
    // Root is completed so getSessionActivityLabel uses flat fallback
    expect(getSessionActivityLabel(nodes)).toBe("reviewer: Reading");
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
