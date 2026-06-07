"use client";

import { useEffect, useRef, useState } from "react";
import type { WorkflowEvent, AgentNodeName } from "@/types/event";
import { AGENT_NODE_ORDER } from "@/types/event";

interface Props {
  events: WorkflowEvent[];
}

const NODE_COLORS: Record<string, string> = {
  information_collection: "#3b82f6",
  analysis: "#8b5cf6",
  feature_analysis: "#6366f1",
  pricing_analysis: "#8b5cf6",
  sentiment_analysis: "#06b6d4",
  positioning_analysis: "#14b8a6",
  role_analysis: "#a855f7",
  gtm_analysis: "#f97316",
  report_writing: "#34d399",
  review: "#f59e0b",
};

const SHORT_NODE: Record<string, string> = {
  information_collection: "collect",
  analysis: "analysis",
  feature_analysis: "feature",
  pricing_analysis: "pricing",
  sentiment_analysis: "sentiment",
  positioning_analysis: "position",
  role_analysis: "role",
  gtm_analysis: "gtm",
  report_writing: "report",
  review: "review",
};

function formatEventMessage(e: WorkflowEvent): string {
  const payload = e.payload as Record<string, unknown> | undefined;
  switch (e.event_type) {
    case "node_start":
      return "Started";
    case "node_progress":
      return String(payload?.message || "Node progress");
    case "node_complete":
      return `Completed in ${payload?.duration_ms || "?"}ms`;
    case "node_error":
      return `ERROR: ${payload?.error_message || ""}`;
    case "tool_call":
      return `Call ${payload?.tool || "tool"}`;
    case "tool_result":
      return `Result from ${payload?.tool || "tool"}`;
    case "review_pass":
      return `PASSED — score: ${payload?.score || "?"}`;
    case "review_fail":
      return `FAILED — ${payload?.feedback || ""}`;
    case "reroute":
      return `Reroute → ${payload?.to_node || payload?.target_node || "analysis"}`;
    case "workflow_complete":
      return "★★★ Workflow COMPLETED ★★★";
    case "workflow_failed":
      return "★★★ Workflow FAILED ★★★";
    default:
      return e.event_type;
  }
}

export function EventConsole({ events }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [filter, setFilter] = useState<"all" | AgentNodeName>("all");

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events]);

  const filtered = filter === "all" ? events : events.filter((e) => e.node_name === filter);

  return (
    <div className="flex flex-col h-full rounded-xl border border-[var(--border)] bg-[var(--bg-card)] overflow-hidden">
      <div className="flex items-center gap-1 px-3 py-2 border-b border-[var(--border)] bg-[var(--bg-elevated)] text-[11px]">
        <span className="text-[var(--text-muted)] mr-1 font-medium">FILTER:</span>
        {(["all", ...AGENT_NODE_ORDER] as const).map(
          (f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-2 py-0.5 rounded transition-colors ${
                filter === f
                  ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]"
                  : "text-[var(--text-muted)] hover:text-[var(--text-primary)]"
              }`}
            >
              {f === "all" ? "ALL" : SHORT_NODE[f]}
            </button>
          )
        )}
        <span className="ml-auto text-[var(--text-muted)] font-mono">{filtered.length} events</span>
      </div>
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-2 font-mono text-[11px] leading-6">
        {filtered.map((e, i) => {
          const nodeName = e.node_name || "review";
          const color = NODE_COLORS[nodeName] || "#a1a1aa";
          const time = new Date(e.created_at).toLocaleTimeString("zh-CN", { hour12: false });
          return (
            <div key={i} className="flex items-baseline gap-2 py-0.5 px-1 hover:bg-[var(--bg-elevated)] rounded">
              <span className="text-[var(--text-muted)] shrink-0 w-14">{time}</span>
              <span className="text-[var(--text-muted)] shrink-0 w-7 text-right">[{e.seq ?? "-"}]</span>
              <span style={{ color }} className="shrink-0 w-16 font-medium">
                {SHORT_NODE[nodeName] || nodeName || "sys"}
              </span>
              <span className="text-[var(--text-secondary)]">{formatEventMessage(e)}</span>
            </div>
          );
        })}
        {filtered.length === 0 && (
          <div className="flex items-center justify-center h-full text-[var(--text-muted)] text-xs">
            Waiting for events...
          </div>
        )}
      </div>
    </div>
  );
}
