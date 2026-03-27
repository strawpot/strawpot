import type { TreeNode } from "@/api/types";

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

  // If this agent is actively doing its own work, show that directly.
  if (node.current_activity) {
    return node.current_activity;
  }

  // Find running children of this agent.
  const runningChildren = nodes.filter(
    (n) => n.parent === agentId && n.status === "running",
  );

  if (runningChildren.length === 0) return null;

  // Single running child with activity — surface it with role prefix.
  if (runningChildren.length === 1) {
    const child = runningChildren[0];
    if (child.current_activity) {
      return `${child.role}: ${child.current_activity}`;
    }
    // Single child, no activity — still mention it.
    return `${child.role} running`;
  }

  // Multiple running children — show aggregate count.
  // If any have activity, pick one to highlight.
  const withActivity = runningChildren.filter((n) => n.current_activity);
  if (withActivity.length > 0) {
    const highlighted = withActivity[withActivity.length - 1];
    return `${runningChildren.length} agents running · ${highlighted.role}: ${highlighted.current_activity}`;
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

  // Multiple roots or no running root — flat fallback (shouldn't happen normally).
  if (roots.length === 0) {
    // All roots are done; check if any node is still running.
    const running = nodes.filter((n) => n.status === "running");
    if (running.length === 0) return null;
    const withActivity = running.filter((n) => n.current_activity);
    if (withActivity.length > 0) {
      const node = withActivity[withActivity.length - 1];
      return `${node.role}: ${node.current_activity}`;
    }
    return `${running.length} agent${running.length === 1 ? "" : "s"} running`;
  }

  // Multiple running roots — aggregate.
  return `${roots.length} agents running`;
}
