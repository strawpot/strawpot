import type { TreeNode } from "@/api/types";

/** A single child activity line: role name + status text. */
export interface ChildActivityLine {
  role: string;
  activity: string;
}

/** Structured activity detail for a node — header plus per-child lines. */
export interface AgentActivityDetail {
  /** Summary header (e.g. "3 agents running", or own activity). */
  header: string;
  /** One line per active sub-agent. Empty when the node shows its own activity. */
  children: ChildActivityLine[];
}

/** Format "role: activity" for a node that has current_activity. */
function formatNodeActivity(node: TreeNode): string {
  return `${node.role}: ${node.current_activity}`;
}

/** Build a ChildActivityLine for a running child node. */
function childLine(node: TreeNode): ChildActivityLine {
  return {
    role: node.role,
    activity: node.current_activity ?? "Working…",
  };
}

/**
 * Compute a human-readable activity label for an agent node.
 *
 * Returns a single-line string for backward compatibility.
 * Use `getAgentActivityDetail` for structured multi-line data.
 */
export function getAgentActivityLabel(
  nodes: TreeNode[],
  agentId: string,
): string | null {
  const detail = getAgentActivityDetail(nodes, agentId);
  return detail?.header ?? null;
}

/**
 * Compute structured activity detail for an agent node.
 *
 * - If the node has its own `current_activity`, returns it as header with no children.
 * - If the node has running child agents, returns an aggregate header
 *   ("3 agents running") plus one line per child with individual activity.
 * - Returns `null` when there's nothing meaningful to display.
 */
export function getAgentActivityDetail(
  nodes: TreeNode[],
  agentId: string,
): AgentActivityDetail | null {
  const node = nodes.find((n) => n.agent_id === agentId);
  if (!node) return null;

  if (node.current_activity) {
    return { header: node.current_activity, children: [] };
  }

  const runningChildren = nodes.filter(
    (n) => n.parent === agentId && n.status === "running",
  );

  if (runningChildren.length === 0) return null;

  if (runningChildren.length === 1) {
    const child = runningChildren[0];
    const header = child.current_activity
      ? formatNodeActivity(child)
      : `${child.role} running`;
    return { header, children: [childLine(child)] };
  }

  // Multiple running children — aggregate header + per-child lines.
  const withActivity = runningChildren.filter((n) => n.current_activity);
  const highlighted = withActivity[withActivity.length - 1];
  const header = highlighted
    ? `${runningChildren.length} agents running · ${formatNodeActivity(highlighted)}`
    : `${runningChildren.length} agents running`;

  return {
    header,
    children: runningChildren.map(childLine),
  };
}

/**
 * Compute the top-level activity label for a session's tree.
 *
 * Returns a single-line string for backward compatibility.
 * Use `getSessionActivityDetail` for structured multi-line data.
 */
export function getSessionActivityLabel(
  nodes: TreeNode[],
): string | null {
  const detail = getSessionActivityDetail(nodes);
  return detail?.header ?? null;
}

/**
 * Compute structured activity detail for a session's tree.
 *
 * Finds the root agent (no parent) and computes its aggregate detail,
 * considering direct children. Falls back to a flat scan if no tree
 * structure is present.
 */
export function getSessionActivityDetail(
  nodes: TreeNode[],
): AgentActivityDetail | null {
  if (nodes.length === 0) return null;

  // Find root node(s) — those without a parent.
  const roots = nodes.filter((n) => n.parent === null && n.status === "running");

  if (roots.length === 1) {
    return getAgentActivityDetail(nodes, roots[0].agent_id);
  }

  // Multiple running roots — aggregate without detail.
  if (roots.length > 1) {
    return { header: `${roots.length} agents running`, children: [] };
  }

  // No running root — flat fallback over all still-running nodes.
  const running = nodes.filter((n) => n.status === "running");
  if (running.length === 0) return null;

  const withActivity = running.filter((n) => n.current_activity);
  const highlighted = withActivity[withActivity.length - 1];
  const header = highlighted
    ? formatNodeActivity(highlighted)
    : `${running.length} agent${running.length === 1 ? "" : "s"} running`;

  return { header, children: running.map(childLine) };
}
