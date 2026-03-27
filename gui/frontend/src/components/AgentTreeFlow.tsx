import { useCallback, useMemo, useState } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  MarkerType,
  type Node,
  type Edge,
  type NodeProps,
  Handle,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { X } from "lucide-react";
import { toast } from "sonner";

import { statusColor as statusVariant, formatDuration } from "@/components/SessionTable";
import { useCancelAgent } from "@/hooks/mutations/use-sessions";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { TreeData, TreeNode, PendingDelegation, DeniedDelegation } from "@/api/types";

/** Map agent status to CSS class for tree nodes (distinct from badge variants). */
function nodeStatusClass(status: string): string {
  switch (status) {
    case "cancelling":
      return "cancelling";
    case "cancelled":
      return "cancelled";
    default:
      return statusVariant(status);
  }
}

const NODE_WIDTH = 180;
const NODE_HEIGHT = 70;
const H_GAP = 24;
const V_GAP = 60;

// ---- Custom node types ----

type AgentNodeData = {
  label: string;
  role: string;
  status: string;
  runtime: string;
  duration_ms: number | null;
  exit_code: number | null;
  pending?: boolean;
  agentId: string;
  onCancel?: (agentId: string, role: string) => void;
};

function AgentFlowNode({ data }: NodeProps<Node<AgentNodeData>>) {
  const cls = data.pending
    ? "agent-flow-node pending"
    : `agent-flow-node ${nodeStatusClass(data.status)}`;

  return (
    <div className={`${cls} relative`}>
      <Handle type="target" position={Position.Top} />
      <div className="agent-flow-role">
        {data.pending ? `[pending: ${data.role}]` : data.role}
      </div>
      {!data.pending && (
        <div className="agent-flow-meta">
          <span className={`status-dot ${nodeStatusClass(data.status)}`} />
          <span>{data.status}</span>
          {data.duration_ms != null && (
            <span>{formatDuration(data.duration_ms)}</span>
          )}
          {data.exit_code != null && <span>exit {data.exit_code}</span>}
        </div>
      )}
      {data.status === "running" && data.onCancel && (
        <button
          className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/90"
          onClick={(e) => {
            e.stopPropagation();
            data.onCancel!(data.agentId, data.role);
          }}
          title="Cancel agent"
        >
          <X className="h-2.5 w-2.5" />
        </button>
      )}
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

const nodeTypes = { agent: AgentFlowNode };

// ---- Descendant counting ----

function countRunningDescendants(nodes: TreeNode[], agentId: string): number {
  const children = nodes.filter(
    (n) => n.parent === agentId && n.status === "running",
  );
  return children.reduce(
    (sum, c) => sum + 1 + countRunningDescendants(nodes, c.agent_id),
    0,
  );
}

// ---- Tree layout ----

interface LayoutItem {
  id: string;
  children: LayoutItem[];
}

function buildLayoutTree(
  nodes: TreeNode[],
  pending: PendingDelegation[],
): LayoutItem[] {
  const byId = new Map(nodes.map((n) => [n.agent_id, n]));
  const childrenOf = new Map<string | null, string[]>();

  for (const n of nodes) {
    const parent = n.parent;
    if (!childrenOf.has(parent)) childrenOf.set(parent, []);
    childrenOf.get(parent)!.push(n.agent_id);
  }

  // Attach pending delegations as pseudo-children
  const pendingByParent = new Map<string, PendingDelegation[]>();
  for (const p of pending) {
    const parent = p.requested_by;
    if (parent && byId.has(parent)) {
      if (!pendingByParent.has(parent)) pendingByParent.set(parent, []);
      pendingByParent.get(parent)!.push(p);
    }
  }

  function build(id: string): LayoutItem {
    const kids = (childrenOf.get(id) || []).map(build);
    const pends = (pendingByParent.get(id) || []).map((p) => ({
      id: `pending-${p.span_id}`,
      children: [],
    }));
    return { id, children: [...kids, ...pends] };
  }

  const roots = childrenOf.get(null) || [];
  return roots.map(build);
}

function subtreeWidth(item: LayoutItem): number {
  if (item.children.length === 0) return NODE_WIDTH;
  return item.children.reduce(
    (sum, c) => sum + subtreeWidth(c) + H_GAP,
    -H_GAP,
  );
}

function assignPositions(
  item: LayoutItem,
  cx: number,
  y: number,
  positions: Map<string, { x: number; y: number }>,
) {
  positions.set(item.id, { x: cx - NODE_WIDTH / 2, y });
  if (item.children.length === 0) return;

  const totalW = subtreeWidth(item);
  let startX = cx - totalW / 2;

  for (const child of item.children) {
    const w = subtreeWidth(child);
    const childCx = startX + w / 2;
    assignPositions(child, childCx, y + NODE_HEIGHT + V_GAP, positions);
    startX += w + H_GAP;
  }
}

// ---- Main component ----

export default function AgentTreeFlow({
  treeData,
  connected,
  runId,
}: {
  treeData: TreeData | null;
  connected: boolean;
  runId: string;
}) {
  return (
    <ReactFlowProvider>
      <AgentTreeFlowInner
        treeData={treeData}
        connected={connected}
        runId={runId}
      />
    </ReactFlowProvider>
  );
}

function AgentTreeFlowInner({
  treeData: tree,
  connected,
  runId,
}: {
  treeData: TreeData | null;
  connected: boolean;
  runId: string;
}) {
  const { fitView } = useReactFlow();
  const cancelAgent = useCancelAgent();

  // Cancel dialog state
  const [cancelTarget, setCancelTarget] = useState<{
    agentId: string;
    role: string;
  } | null>(null);
  const [forceCancel, setForceCancel] = useState(false);

  const descendantCount =
    cancelTarget && tree
      ? countRunningDescendants(tree.nodes, cancelTarget.agentId)
      : 0;

  const handleCancelRequest = useCallback(
    (agentId: string, role: string) => {
      setCancelTarget({ agentId, role });
      setForceCancel(false);
    },
    [],
  );

  const handleCancelConfirm = useCallback(async () => {
    if (!cancelTarget) return;
    try {
      await cancelAgent.mutateAsync({
        runId,
        agentId: cancelTarget.agentId,
        force: forceCancel,
      });
      toast.success(`Cancel signal sent for ${cancelTarget.role}`);
    } catch (err) {
      toast.error(
        `Failed to cancel agent: ${err instanceof Error ? err.message : "Unknown error"}`,
      );
    }
    setCancelTarget(null);
  }, [cancelTarget, cancelAgent, runId, forceCancel]);

  const handleReset = useCallback(() => {
    fitView({ duration: 300 });
  }, [fitView]);

  const { flowNodes, flowEdges } = useMemo(() => {
    if (!tree) return { flowNodes: [], flowEdges: [] };

    const layoutRoots = buildLayoutTree(tree.nodes, tree.pending_delegations);

    // Compute positions
    const positions = new Map<string, { x: number; y: number }>();
    let offsetX = 0;
    for (const root of layoutRoots) {
      const w = subtreeWidth(root);
      const cx = offsetX + w / 2;
      assignPositions(root, cx, 0, positions);
      offsetX += w + H_GAP * 2;
    }

    // Build flow nodes
    const nodeMap = new Map(tree.nodes.map((n) => [n.agent_id, n]));
    const pendingMap = new Map(
      tree.pending_delegations.map((p) => [`pending-${p.span_id}`, p]),
    );

    const flowNodes: Node<AgentNodeData>[] = [];

    for (const [id, pos] of positions) {
      const agent = nodeMap.get(id);
      const pend = pendingMap.get(id);

      if (agent) {
        flowNodes.push({
          id,
          type: "agent",
          position: pos,
          data: {
            label: agent.role,
            role: agent.role,
            status: agent.status,
            runtime: agent.runtime,
            duration_ms: agent.duration_ms,
            exit_code: agent.exit_code,
            agentId: agent.agent_id,
            onCancel: handleCancelRequest,
          },
        });
      } else if (pend) {
        flowNodes.push({
          id,
          type: "agent",
          position: pos,
          data: {
            label: pend.role,
            role: pend.role,
            status: "running",
            runtime: "",
            duration_ms: null,
            exit_code: null,
            pending: true,
            agentId: "",
          },
        });
      }
    }

    // Build edges
    const flowEdges: Edge[] = [];
    for (const n of tree.nodes) {
      if (n.parent) {
        flowEdges.push({
          id: `e-${n.parent}-${n.agent_id}`,
          source: n.parent,
          target: n.agent_id,
          type: "smoothstep",
          markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
        });
      }
    }
    for (const p of tree.pending_delegations) {
      if (p.requested_by) {
        flowEdges.push({
          id: `e-${p.requested_by}-pending-${p.span_id}`,
          source: p.requested_by,
          target: `pending-${p.span_id}`,
          type: "smoothstep",
          markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
          style: { strokeDasharray: "5 3" },
        });
      }
    }

    return { flowNodes, flowEdges };
  }, [tree, handleCancelRequest]);

  if (!tree) {
    return (
      <div className="agent-tree">
        <p className="agent-meta">
          {connected ? "Loading tree..." : "Connecting..."}
        </p>
      </div>
    );
  }

  return (
    <div>
      <div className="react-flow-wrapper">
        <ReactFlow
          nodes={flowNodes}
          edges={flowEdges}
          nodeTypes={nodeTypes}
          fitView
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          proOptions={{ hideAttribution: true }}
        />
        <button className="tree-reset-btn" onClick={handleReset}>
          Reset View
        </button>
      </div>

      {tree.denied_delegations.length > 0 && (
        <div className="denied-list">
          <strong>Denied delegations:</strong>
          {tree.denied_delegations.map((d: DeniedDelegation) => (
            <span key={d.span_id} className="denied-item">
              {d.role} ({d.reason})
            </span>
          ))}
        </div>
      )}

      {/* Cancel confirmation dialog */}
      <Dialog
        open={!!cancelTarget}
        onOpenChange={(open) => {
          if (!open) setCancelTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Cancel Agent</DialogTitle>
            <DialogDescription>
              Cancel <strong>{cancelTarget?.role}</strong>?
              {descendantCount > 0
                ? ` This will also cancel ${descendantCount} running descendant${descendantCount === 1 ? "" : "s"}.`
                : " This agent has no running descendants."}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">
              Agent ID: <code>{cancelTarget?.agentId.slice(0, 16)}</code>
            </p>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={forceCancel}
                onChange={(e) => setForceCancel(e.target.checked)}
                className="h-4 w-4 rounded border-input"
              />
              Force cancel (skip graceful shutdown)
            </label>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setCancelTarget(null)}
            >
              Keep Running
            </Button>
            <Button
              variant="destructive"
              onClick={handleCancelConfirm}
              disabled={cancelAgent.isPending}
            >
              {cancelAgent.isPending ? "Cancelling..." : "Cancel Agent"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
