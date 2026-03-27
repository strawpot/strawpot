import type { TreeNode } from "@/api/types";

/** Format "role: activity" for a node that has current_activity. */
function formatNodeActivity(node: TreeNode): string {
  return `${node.role}: ${node.current_activity}`;
}

/**
 * Compute a human-readable activity label for an agent node.
 *
 * - If the node has its own `current_activity` (actively using a tool), show that.
 * - If the node has running child agents, show an aggregate summary
 *   like "3 agents running" to keep parent nodes low-noise.
 * - If only one child is running with activity, surface it as
 *   "{role}: {activity}" for extra visibility.
 * - Returns `null` when there's nothing meaningful to display (caller
 *   should fall back to "Working…").
 */
export function getAgentActivityLabel(
  nodes: TreeNode[],
  agentId: string,
): string | null {
  const node = nodes.find((n) => n.agent_id === agentId);
  if (!node) return null;

  if (node.current_activity) {
    return node.current_activity;
  }

  const runningChildren = nodes.filter(
    (n) => n.parent === agentId && n.status === "running",
  );

  if (runningChildren.length === 0) return null;

  if (runningChildren.length === 1) {
    const child = runningChildren[0];
    return child.current_activity
      ? formatNodeActivity(child)
      : `${child.role} running`;
  }

  // Multiple running children — show aggregate count, highlight the latest active one.
  const withActivity = runningChildren.filter((n) => n.current_activity);
  const highlighted = withActivity[withActivity.length - 1];
  if (highlighted) {
    return `${runningChildren.length} agents running · ${formatNodeActivity(highlighted)}`;
  }

  return `${runningChildren.length} agents running`;
}

/**
 * Compute the top-level activity label for a session's tree.
 *
 * Finds the root agent (no parent) and computes its aggregate label,
 * considering all descendants. Falls back to a flat scan if no tree
 * structure is present.
 */
export function getSessionActivityLabel(
  nodes: TreeNode[],
): string | null {
  if (nodes.length === 0) return null;

  // Find root node(s) — those without a parent.
  const roots = nodes.filter((n) => n.parent === null && n.status === "running");

  if (roots.length === 1) {
    return getAgentActivityLabel(nodes, roots[0].agent_id);
  }

  // Multiple running roots — aggregate without detail.
  if (roots.length > 1) {
    return `${roots.length} agents running`;
  }

  // No running root — flat fallback over all still-running nodes.
  const running = nodes.filter((n) => n.status === "running");
  if (running.length === 0) return null;

  const withActivity = running.filter((n) => n.current_activity);
  const highlighted = withActivity[withActivity.length - 1];
  if (highlighted) {
    return formatNodeActivity(highlighted);
  }
  return `${running.length} agent${running.length === 1 ? "" : "s"} running`;
}
