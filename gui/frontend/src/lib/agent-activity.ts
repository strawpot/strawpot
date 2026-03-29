import type { TreeNode } from "@/api/types";

/** Structured activity detail for a node — header plus most-recent child activity. */
export interface AgentActivityDetail {
  /** Summary header (e.g. "3 agents running", or own activity). */
  header: string;
  /** Most-recently-updated sub-agent activity, or null when showing own activity. */
  childActivity: string | null;
}

/** Format "role: activity" for a node that has current_activity. */
function formatNodeActivity(node: TreeNode): string {
  return `${node.role}: ${node.current_activity}`;
}

/** Build "N agent(s) running" header. */
function formatRunningHeader(count: number): string {
  return `${count} agent${count === 1 ? "" : "s"} running`;
}

/**
 * Build detail from a set of running child nodes.
 *
 * @param runningNodes — the running *child* nodes (used for activity lookup).
 * @param totalCount   — total running agents to display in the header
 *                        (includes the parent).  Defaults to runningNodes.length
 *                        for the flat-fallback path where there is no parent.
 */
function buildRunningDetail(
  runningNodes: TreeNode[],
  totalCount?: number,
): AgentActivityDetail {
  const count = totalCount ?? runningNodes.length;
  const withActivity = runningNodes.filter((n) => n.current_activity);
  const mostRecent = withActivity[withActivity.length - 1];
  const lastChild = runningNodes[runningNodes.length - 1];
  return {
    header: formatRunningHeader(count),
    childActivity: mostRecent
      ? formatNodeActivity(mostRecent)
      : lastChild
        ? `${lastChild.role}: Working…`
        : "Working…",
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
 * - If the node has running child agents, returns an aggregate header
 *   ("3 agents running") plus the most-recently-updated child's activity.
 *   The count includes the parent itself (parent + children).
 * - If the node has its own `current_activity` but no running children,
 *   returns it as header with no child activity.
 * - Returns `null` when there's nothing meaningful to display.
 */
export function getAgentActivityDetail(
  nodes: TreeNode[],
  agentId: string,
): AgentActivityDetail | null {
  const node = nodes.find((n) => n.agent_id === agentId);
  if (!node) return null;

  // Running children take priority — show aggregate with child detail.
  const runningChildren = nodes.filter(
    (n) => n.parent === agentId && n.status === "running",
  );

  if (runningChildren.length > 0) {
    // +1 to include the parent node itself in the total count.
    return buildRunningDetail(runningChildren, runningChildren.length + 1);
  }

  // No running children — fall back to own activity.
  if (node.current_activity) {
    return { header: node.current_activity, childActivity: null };
  }

  return null;
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
    return { header: formatRunningHeader(roots.length), childActivity: null };
  }

  // No running root — flat fallback over all still-running nodes.
  const running = nodes.filter((n) => n.status === "running");
  if (running.length === 0) return null;

  return buildRunningDetail(running);
}
