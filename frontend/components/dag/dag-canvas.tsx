"use client";

import { useMemo, useCallback } from "react";
import { ReactFlow, Background, Controls, type Node, type Edge, MarkerType } from "reactflow";
import "reactflow/dist/style.css";
import { DagNode } from "./dag-node";
import type { AgentNodeName } from "@/types/event";

const nodeTypes = { dagNode: DagNode };

const NODE_DEFINITIONS: Array<{ id: AgentNodeName; label: string; position: { x: number; y: number } }> = [
  { id: "information_collection", label: "CollectionAgent\n信息采集", position: { x: 160, y: 0 } },
  { id: "analysis", label: "AnalysisAgent\n多维分析", position: { x: 160, y: 150 } },
  { id: "report_writing", label: "ReportAgent\n报告撰写", position: { x: 160, y: 300 } },
  { id: "review", label: "ReviewAgent\n质量审查", position: { x: 160, y: 450 } },
];

export type NodeStatus = "idle" | "active" | "completed" | "failed" | "rerouted";

interface Props {
  nodeStates: Record<AgentNodeName, { status: NodeStatus; message?: string; duration_ms?: number }>;
  hasReroute: boolean;
  onRetry?: (node: AgentNodeName) => void;
}

export function DagCanvas({ nodeStates, hasReroute, onRetry }: Props) {
  const nodes: Node[] = useMemo(
    () =>
      NODE_DEFINITIONS.map((def) => ({
        id: def.id,
        type: "dagNode",
        position: def.position,
        data: {
          label: def.label,
          status: nodeStates[def.id]?.status || "idle",
          message: nodeStates[def.id]?.message,
          duration_ms: nodeStates[def.id]?.duration_ms,
          onRetry: onRetry ? () => onRetry(def.id) : undefined,
        },
      })),
    [nodeStates, onRetry]
  );

  const edges: Edge[] = useMemo(() => {
    const mainEdges: Edge[] = [
      { id: "e-c-a", source: "information_collection", target: "analysis" },
      { id: "e-a-r", source: "analysis", target: "report_writing" },
      { id: "e-r-rv", source: "report_writing", target: "review" },
    ].map((e) => ({
      ...e,
      animated: nodeStates[e.source as AgentNodeName]?.status === "completed",
      style: { stroke: "var(--border)", strokeWidth: 2, strokeDasharray: "6 4" },
      markerEnd: { type: MarkerType.ArrowClosed, color: "var(--text-muted)" },
    }));

    if (hasReroute) {
      mainEdges.push({
        id: "e-reroute",
        source: "review",
        target: "analysis",
        animated: true,
        style: { stroke: "#f59e0b", strokeWidth: 2.5, strokeDasharray: "8 4" },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#f59e0b" },
        label: "REROUTE",
        labelStyle: { fill: "#f59e0b", fontSize: 10, fontWeight: 700 },
      } as Edge);
    }

    return mainEdges;
  }, [nodeStates, hasReroute]);

  return (
    <div className="h-full w-full rounded-2xl border border-[var(--border)] bg-dot-grid overflow-hidden">
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView preventScrolling={false}>
        <Background color="var(--border)" gap={24} size={1} />
        <Controls className="[&>button]:!bg-[var(--bg-card)] [&>button]:!border-[var(--border)] [&>button]:!text-[var(--text-secondary)] [&>button]:!rounded-lg" />
      </ReactFlow>
    </div>
  );
}
