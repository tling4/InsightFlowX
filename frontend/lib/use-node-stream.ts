"use client";

import { useState, useCallback } from "react";
import type {
  AgentNodeName,
  NodeProgressEntry,
  NodeProgressLevel,
  WorkflowEvent,
} from "@/types/event";
import { AGENT_NODE_ORDER } from "@/types/event";

const NODE_ORDER: AgentNodeName[] = AGENT_NODE_ORDER;

type NodeEntries = Record<AgentNodeName, NodeProgressEntry[]>;

interface ProgressState {
  activeNode: AgentNodeName | null;
  selectedNode: AgentNodeName | null;
  entries: NodeEntries;
}

function createEmptyEntries(): NodeEntries {
  return NODE_ORDER.reduce((acc, node) => {
    acc[node] = [];
    return acc;
  }, {} as NodeEntries);
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

function buildNodeStartMessage(node: AgentNodeName, payload: Record<string, unknown> | undefined): string {
  const summary = payload?.input_summary as Record<string, unknown> | undefined;
  if (!summary) return "开始执行该节点";

  const phase = summary.phase as string | undefined;
  const target = summary.target_product as string | undefined;
  const competitors = summary.competitors_count as number | undefined;
  const products = summary.products_count as number | undefined;
  const sources = summary.source_count as number | undefined;

  switch (node) {
    case "information_collection":
      return `开始采集信息：目标产品「${target || "未知"}」，竞品 ${competitors ?? "?"} 个`;
    case "analysis":
      return `开始多维分析：${products ?? "?"} 个产品，${sources ?? "?"} 条来源`;
    case "report_writing":
      return `开始撰写报告：目标产品「${target || "未知"}」`;
    case "review":
      return `开始审查：${phase === "reviewing" ? "评估报告质量" : "进入审查阶段"}`;
    default:
      return `开始执行${node}节点`;
  }
}

function buildNodeCompleteMessage(node: AgentNodeName, payload: Record<string, unknown> | undefined): string {
  const summary = (payload?.output_summary as Record<string, unknown>) || {};
  const duration = payload?.duration_ms as number | undefined;
  const parts: string[] = [];

  switch (node) {
    case "information_collection": {
      const collected = summary.collected_competitors as number | undefined;
      const totalSources = summary.total_sources as number | undefined;
      const failed = summary.failed_competitors as number | undefined;
      if (collected !== undefined) parts.push(`覆盖 ${collected} 个产品`);
      if (totalSources !== undefined) parts.push(`汇总 ${totalSources} 条来源`);
      if (failed !== undefined && failed > 0) parts.push(`${failed} 个产品采集失败`);
      break;
    }
    case "analysis": {
      const dims = summary.dimensions_count as number | undefined;
      const features = summary.feature_items as number | undefined;
      const pricing = summary.pricing_plans as number | undefined;
      if (dims !== undefined) parts.push(`分析 ${dims} 个维度`);
      if (features !== undefined) parts.push(`${features} 项功能对比`);
      if (pricing !== undefined) parts.push(`${pricing} 个定价方案`);
      break;
    }
    case "report_writing": {
      const sections = summary.sections_count as number | undefined;
      const citations = summary.citations_count as number | undefined;
      if (sections !== undefined) parts.push(`生成 ${sections} 个章节`);
      if (citations !== undefined) parts.push(`引用 ${citations} 条来源`);
      break;
    }
    case "review": {
      const passed = summary.passed as boolean | undefined;
      const score = summary.score as number | undefined;
      if (passed !== undefined) parts.push(passed ? "审查通过" : "审查未通过");
      if (score !== undefined) parts.push(`评分 ${score}`);
      break;
    }
  }

  if (duration !== undefined) {
    parts.push(`用时 ${duration >= 1000 ? `${(duration / 1000).toFixed(1)}s` : `${duration}ms`}`);
  }

  return parts.length > 0 ? parts.join("，") : "该节点已完成";
}

function buildToolCallStage(payload: Record<string, unknown> | undefined): string {
  const tool = String(payload?.tool || "tool");
  if (tool === "tavily.search") {
    const product = String(payload?.product || "");
    return `搜索: ${product}`;
  }
  if (tool === "competitor_resolver") {
    return "竞品解析";
  }
  return `调用: ${tool}`;
}

function buildToolCallMessage(payload: Record<string, unknown> | undefined): string {
  const tool = String(payload?.tool || "");
  if (tool === "tavily.search") {
    const queries = payload?.queries as string[] | undefined;
    if (queries && queries.length > 0) {
      return `执行 ${queries.length} 条搜索查询：${queries.map((q) => `「${q}」`).join("、")}`;
    }
    return "执行搜索查询";
  }
  if (tool === "competitor_resolver") {
    const product = String(payload?.target_product || "");
    return `为目标产品「${product}」解析竞品实体`;
  }
  return "";
}

function buildToolResultStage(payload: Record<string, unknown> | undefined): string {
  const tool = String(payload?.tool || "tool");
  if (tool === "tavily.search") {
    const product = String(payload?.product || "");
    const count = payload?.source_count as number | undefined;
    return `${product}: ${count ?? 0} 条结果`;
  }
  if (tool === "competitor_resolver") {
    return "竞品解析完成";
  }
  return `${tool} 完成`;
}

function buildToolResultMessage(payload: Record<string, unknown> | undefined): string {
  const tool = String(payload?.tool || "");
  if (tool === "competitor_resolver") {
    const dropped = payload?.dropped as string[] | undefined;
    const added = payload?.added as string[] | undefined;
    const resolved = payload?.resolved_competitors as string[] | undefined;
    const parts: string[] = [];
    if (dropped && dropped.length > 0) parts.push(`移除 ${dropped.length} 个无效候选：${dropped.join("、")}`);
    if (added && added.length > 0) parts.push(`补充 ${added.length} 个相关竞品：${added.join("、")}`);
    if (resolved && resolved.length > 0) parts.push(`最终竞品列表：${resolved.join("、")}`);
    return parts.join("\n") || "竞品解析完成";
  }
  return "";
}

function buildLlmResponseMessage(
  node: AgentNodeName,
  payload: Record<string, unknown> | undefined,
): string {
  const task = String(payload?.model_task || "");
  const parts: string[] = [];
  if (task) parts.push(`任务: ${task}`);

  switch (node) {
    case "analysis": {
      const features = payload?.feature_items as number | undefined;
      const plans = payload?.pricing_plans as number | undefined;
      if (features !== undefined) parts.push(`对比 ${features} 项功能`);
      if (plans !== undefined) parts.push(`${plans} 个定价方案`);
      break;
    }
    case "report_writing": {
      const sections = payload?.sections_count as number | undefined;
      if (sections !== undefined) parts.push(`生成 ${sections} 个章节`);
      break;
    }
    case "review": {
      const score = payload?.score as number | undefined;
      const passed = payload?.passed as boolean | undefined;
      if (score !== undefined) parts.push(`评分 ${score}`);
      if (passed !== undefined) parts.push(passed ? "通过" : "未通过");
      break;
    }
  }
  return parts.join("，") || "LLM 调用完成";
}

function buildReviewPassMessage(payload: Record<string, unknown> | undefined): string {
  const score = payload?.score as number | undefined;
  const checks = payload?.checks as Array<{ dimension: string; passed: boolean; detail: string }> | undefined;
  const parts: string[] = [];
  if (score !== undefined) parts.push(`综合评分 ${score}`);
  if (checks && checks.length > 0) {
    parts.push(checks.map((c) => `${c.passed ? "✓" : "✗"} ${c.detail || c.dimension}`).join("\n"));
  }
  return parts.join("\n") || "审查通过";
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
      return makeEntry(
        node,
        event.event_type,
        "node_start",
        buildNodeStartMessage(node, payload),
        createdAt,
        "info",
        event.seq,
      );
    case "node_complete":
      return makeEntry(
        node,
        event.event_type,
        "node_complete",
        buildNodeCompleteMessage(node, payload),
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
    case "tool_call":
      return makeEntry(
        node,
        event.event_type,
        buildToolCallStage(payload),
        buildToolCallMessage(payload),
        createdAt,
        "info",
        event.seq,
      );
    case "tool_result":
      return makeEntry(
        node,
        event.event_type,
        buildToolResultStage(payload),
        buildToolResultMessage(payload),
        createdAt,
        "success",
        event.seq,
      );
    case "llm_response":
      return makeEntry(
        node,
        event.event_type,
        "LLM 调用完成",
        buildLlmResponseMessage(node, payload),
        createdAt,
        "success",
        event.seq,
      );
    case "review_pass":
      return makeEntry(
        node,
        event.event_type,
        "审查通过",
        buildReviewPassMessage(payload),
        createdAt,
        "success",
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
    case "workflow_start":
      return makeEntry(node, event.event_type, "workflow_start", "工作流启动，开始执行 DAG 编排。", createdAt, "info", event.seq);
    case "workflow_resumed":
      return makeEntry(node, event.event_type, "workflow_resumed", "工作流已恢复，从断点继续执行。", createdAt, "info", event.seq);
    case "review_failed_max_revisions":
      return makeEntry(
        node,
        event.event_type,
        "已达最大修订次数",
        `已修订 ${payload?.revision_count || "?"} 次（上限 ${payload?.max_revisions || "?"}），停止回退。`,
        createdAt,
        "warning",
        event.seq,
      );
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
