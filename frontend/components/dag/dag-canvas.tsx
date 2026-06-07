"use client";

import { useMemo, useRef, useCallback } from "react";
import { ReactFlow, Background, Controls, type Node, type Edge, MarkerType } from "reactflow";
import "reactflow/dist/style.css";
import { DagNode } from "./dag-node";
import type { DagNodeData } from "./dag-node";
import type { AgentNodeName } from "@/types/event";

const nodeTypes = { dagNode: DagNode };

const NODE_DEFINITIONS: Array<{ id: AgentNodeName; label: string; position: { x: number; y: number } }> = [
  { id: "information_collection", label: "CollectionAgent\n信息采集", position: { x: 160, y: 0 } },
  { id: "analysis", label: "AnalysisAgent\n分析编排", position: { x: 160, y: 140 } },
  { id: "feature_analysis", label: "FeatureAnalysis\n功能矩阵", position: { x: 0, y: 300 } },
  { id: "pricing_analysis", label: "PricingAnalysis\n定价分析", position: { x: 160, y: 300 } },
  { id: "sentiment_analysis", label: "SentimentAnalysis\n用户反馈", position: { x: 320, y: 300 } },
  { id: "positioning_analysis", label: "PositioningAnalysis\n定位判断", position: { x: 0, y: 460 } },
  { id: "role_analysis", label: "RoleAnalysis\n角色判断", position: { x: 160, y: 460 } },
  { id: "gtm_analysis", label: "GTMAnalysis\n上市增长", position: { x: 320, y: 460 } },
  { id: "report_writing", label: "ReportAgent\n报告撰写", position: { x: 160, y: 620 } },
  { id: "review", label: "ReviewAgent\n质量审查", position: { x: 160, y: 780 } },
];

export type NodeStatus = "idle" | "active" | "completed" | "failed" | "rerouted";

interface Props {
  nodeStates: Record<AgentNodeName, { status: NodeStatus; message?: string; duration_ms?: number }>;
  hasReroute: boolean;
  rerouteTarget?: AgentNodeName;
  onRetry?: (node: AgentNodeName) => void;
}

export function DagCanvas({ nodeStates, hasReroute, rerouteTarget = "analysis", onRetry }: Props) {
  const dataCacheRef = useRef<Map<string, DagNodeData>>(new Map());
  const rfInstance = useRef<any>(null);

  const onInit = useCallback((instance: any) => {
    rfInstance.current = instance;
    // 延迟 fitView，等容器布局完成后再计算
    setTimeout(() => instance.fitView({ padding: 0.2, duration: 0 }), 100);
  }, []);

  const nodes: Node[] = useMemo(
    () =>
      NODE_DEFINITIONS.map((def) => {
        const newStatus = nodeStates[def.id]?.status ?? "idle";
        const newMessage = nodeStates[def.id]?.message;
        const newDuration = nodeStates[def.id]?.duration_ms;

        const cached = dataCacheRef.current.get(def.id);
        if (
          cached &&
          cached.status === newStatus &&
          cached.message === newMessage &&
          cached.duration_ms === newDuration
        ) {
          return {
            id: def.id,
            type: "dagNode",
            position: def.position,
            data: cached,
          };
        }

        const newData: DagNodeData = {
          label: def.label,
          status: newStatus,
          message: newMessage,
          duration_ms: newDuration,
          onRetry: onRetry ? () => onRetry(def.id) : undefined,
        };
        dataCacheRef.current.set(def.id, newData);

        return {
          id: def.id,
          type: "dagNode",
          position: def.position,
          data: newData,
        };
      }),
    [nodeStates, onRetry]
  );

  const edges: Edge[] = useMemo(() => {
    const mainEdges: Edge[] = [
      { id: "e-c-a", source: "information_collection", target: "analysis" },
      { id: "e-a-f", source: "analysis", target: "feature_analysis" },
      { id: "e-f-p", source: "feature_analysis", target: "pricing_analysis" },
      { id: "e-p-s", source: "pricing_analysis", target: "sentiment_analysis" },
      { id: "e-s-pos", source: "sentiment_analysis", target: "positioning_analysis" },
      { id: "e-pos-role", source: "positioning_analysis", target: "role_analysis" },
      { id: "e-role-gtm", source: "role_analysis", target: "gtm_analysis" },
      { id: "e-gtm-r", source: "gtm_analysis", target: "report_writing" },
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
        target: rerouteTarget,
        animated: true,
        style: { stroke: "#f59e0b", strokeWidth: 2.5, strokeDasharray: "8 4" },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#f59e0b" },
      } as Edge);
    }

    return mainEdges;
  }, [nodeStates, hasReroute, rerouteTarget]);

  return (
    <div className="h-full w-full min-h-[300px] min-w-[200px] rounded-2xl border border-[var(--border)] bg-dot-grid overflow-hidden">
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onInit={onInit} fitView fitViewOptions={{ padding: 0.2, duration: 0, minZoom: 0.3, maxZoom: 2 }} preventScrolling={false}>
        <Background color="var(--border)" gap={24} size={1} />
        <Controls className="[&>button]:!bg-[var(--bg-card)] [&>button]:!border-[var(--border)] [&>button]:!text-[var(--text-secondary)] [&>button]:!rounded-lg" />
      </ReactFlow>
    </div>
  );
}
