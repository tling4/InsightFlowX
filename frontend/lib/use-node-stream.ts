"use client";

import { useState, useCallback } from "react";
import type {
  AgentNodeName,
  NodeProgressEntry,
  NodeProgressLevel,
  WorkflowEvent,
} from "@/types/event";

const NODE_ORDER: AgentNodeName[] = [
  "information_collection",
  "analysis",
  "report_writing",
  "review",
];

type NodeEntries = Record<AgentNodeName, NodeProgressEntry[]>;

interface ProgressState {
  activeNode: AgentNodeName | null;
  selectedNode: AgentNodeName | null;
  entries: NodeEntries;
}

function createEmptyEntries(): NodeEntries {
  return {
    information_collection: [],
    analysis: [],
    report_writing: [],
    review: [],
  };
}

function isAgentNodeName(value: unknown): value is AgentNodeName {
  return typeof value === "string" && NODE_ORDER.includes(value as AgentNodeName);
}

function makeEntry(
  node: AgentNodeName,
  eventType: NodeProgressEntry["event_type"],
  stage: string,
  message: string,
  createdAt: string,
  level: NodeProgressLevel = "info",
  seq?: number,
): NodeProgressEntry {
  return {
    node,
    stage,
    message,
    level,
    created_at: createdAt,
    seq,
    event_type: eventType,
  };
}

function fallbackNode(activeNode: AgentNodeName | null): AgentNodeName {
  return activeNode ?? "review";
}

function eventToEntry(
  event: WorkflowEvent,
  activeNode: AgentNodeName | null,
): NodeProgressEntry | null {
  const payload = event.payload as Record<string, unknown> | undefined;
  const node = isAgentNodeName(event.node_name) ? event.node_name : fallbackNode(activeNode);
  const createdAt = event.created_at || new Date().toISOString();

  switch (event.event_type) {
    case "node_progress":
      return makeEntry(
        node,
        event.event_type,
        String(payload?.stage || "progress"),
        String(payload?.message || ""),
        createdAt,
        (payload?.level as NodeProgressLevel) || "info",
        event.seq,
      );
    case "node_start":
      return makeEntry(node, event.event_type, "node_start", "开始执行该节点", createdAt, "info", event.seq);
    case "node_complete":
      return makeEntry(
        node,
        event.event_type,
        "node_complete",
        `该节点已完成${payload?.duration_ms ? `，用时 ${payload.duration_ms}ms` : ""}`,
        createdAt,
        "success",
        event.seq,
      );
    case "node_error":
      return makeEntry(
        node,
        event.event_type,
        "node_error",
        `执行失败：${String(payload?.error_message || "未知错误")}`,
        createdAt,
        "error",
        event.seq,
      );
    case "review_fail":
      return makeEntry(
        node,
        event.event_type,
        "review_fail",
        `当前结果未通过审查：${String(payload?.feedback || "需要继续修订")}`,
        createdAt,
        "warning",
        event.seq,
      );
    case "reroute":
      return makeEntry(
        node,
        event.event_type,
        "reroute",
        `系统建议回退到 ${String(payload?.to_node || payload?.target_node || "analysis")} 节点重新执行`,
        createdAt,
        "warning",
        event.seq,
      );
    case "workflow_paused":
      return makeEntry(
        node,
        event.event_type,
        "workflow_paused",
        String(payload?.pause_reason || "工作流已暂停，等待人工决策"),
        createdAt,
        "warning",
        event.seq,
      );
    case "workflow_failed":
      if (payload?.error_code === "REVIEW_FAILED") {
        return null;
      }
      return makeEntry(
        node,
        event.event_type,
        "workflow_failed",
        `工作流失败：${String((event as { error_message?: string }).error_message || payload?.error_message || "执行异常")}`,
        createdAt,
        "error",
        event.seq,
      );
    case "workflow_complete":
      return makeEntry(node, event.event_type, "workflow_complete", "工作流已完成，结果已生成。", createdAt, "success", event.seq);
    default:
      return null;
  }
}

export function useNodeStream() {
  const [state, setState] = useState<ProgressState>({
    activeNode: null,
    selectedNode: null,
    entries: createEmptyEntries(),
  });

  const setSelectedNode = useCallback((node: AgentNodeName) => {
    setState((prev) => ({ ...prev, selectedNode: node }));
  }, []);

  const setActiveNode = useCallback((node: AgentNodeName) => {
    setState((prev) => ({
      ...prev,
      activeNode: node,
      selectedNode: node,
    }));
  }, []);

  const appendEvent = useCallback((event: WorkflowEvent) => {
    setState((prev) => {
      const entry = eventToEntry(event, prev.activeNode);
      const nextActiveNode =
        event.event_type === "node_start" && isAgentNodeName(event.node_name)
          ? event.node_name
          : prev.activeNode;
      const nextSelectedNode =
        event.event_type === "node_start" && isAgentNodeName(event.node_name)
          ? event.node_name
          : prev.selectedNode;

      if (!entry) {
        return {
          ...prev,
          activeNode: nextActiveNode,
          selectedNode: nextSelectedNode,
        };
      }

      return {
        activeNode: nextActiveNode ?? entry.node,
        selectedNode: nextSelectedNode ?? entry.node,
        entries: {
          ...prev.entries,
          [entry.node]: [...prev.entries[entry.node], entry],
        },
      };
    });
  }, []);

  const rebuildFromEvents = useCallback((events: WorkflowEvent[]) => {
    const nextEntries = createEmptyEntries();
    let activeNode: AgentNodeName | null = null;

    for (const event of [...events].sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0))) {
      if (event.event_type === "node_start" && isAgentNodeName(event.node_name)) {
        activeNode = event.node_name;
      }
      const entry = eventToEntry(event, activeNode);
      if (entry) {
        nextEntries[entry.node].push(entry);
      }
    }

    const selectedNode =
      activeNode
      ?? NODE_ORDER.find((node) => nextEntries[node].length > 0)
      ?? null;

    setState({
      activeNode,
      selectedNode,
      entries: nextEntries,
    });
  }, []);

  return {
    ...state,
    appendEvent,
    rebuildFromEvents,
    setActiveNode,
    setSelectedNode,
  };
}
