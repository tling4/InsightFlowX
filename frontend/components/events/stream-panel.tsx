"use client";

import { useEffect, useMemo, useRef } from "react";
import type { AgentNodeName, NodeProgressEntry } from "@/types/event";
import { AGENT_NODE_ORDER } from "@/types/event";

const NODE_LABELS: Record<AgentNodeName, string> = {
  information_collection: "CollectionAgent",
  analysis: "AnalysisAgent",
  feature_analysis: "FeatureAnalysis",
  pricing_analysis: "PricingAnalysis",
  sentiment_analysis: "SentimentAnalysis",
  positioning_analysis: "PositioningAnalysis",
  role_analysis: "RoleAnalysis",
  gtm_analysis: "GTMAnalysis",
  report_writing: "ReportAgent",
  review: "ReviewAgent",
};

const LEVEL_STYLES: Record<string, string> = {
  info: "border-sky-500/20 bg-sky-500/10 text-sky-700 dark:text-sky-200",
  success: "border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-200",
  warning: "border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-200",
  error: "border-rose-500/20 bg-rose-500/10 text-rose-700 dark:text-rose-200",
};

interface Props {
  activeNode: AgentNodeName | null;
  selectedNode: AgentNodeName | null;
  entries: Record<AgentNodeName, NodeProgressEntry[]>;
  onSelectNode: (node: AgentNodeName) => void;
}

export function StreamPanel({ activeNode, selectedNode, entries, onSelectNode }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [selectedNode, entries]);

  const orderedNodes = useMemo(
    () => AGENT_NODE_ORDER,
    [],
  );

  const currentEntries = selectedNode ? entries[selectedNode] || [] : [];

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="px-5 py-3 border-b border-[var(--border)] bg-[var(--bg-elevated)] space-y-3">
        <div className="flex items-center gap-2">
          {activeNode ? (
            <>
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-400" />
              </span>
              <span className="text-xs font-medium text-[var(--text-primary)]">
                当前执行: {NODE_LABELS[activeNode]}
              </span>
            </>
          ) : (
            <span className="text-xs font-medium text-[var(--text-primary)]">节点过程叙述</span>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {orderedNodes.map((node) => {
            const isSelected = selectedNode === node;
            const count = entries[node]?.length || 0;
            const isActive = activeNode === node;
            return (
              <button
                key={node}
                onClick={() => onSelectNode(node)}
                className={`rounded-full border px-2.5 py-1 text-[11px] transition-colors ${
                  isSelected
                    ? "border-emerald-500/40 bg-emerald-500/10 text-[var(--text-primary)]"
                    : "border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text-primary)]"
                }`}
              >
                {NODE_LABELS[node]}
                {isActive ? " · 运行中" : ""}
                {count > 0 ? ` · ${count}` : ""}
              </button>
            );
          })}
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto p-5 space-y-3">
        {currentEntries.length > 0 ? (
          currentEntries.map((entry, index) => (
            <div
              key={`${entry.node}-${entry.seq ?? index}-${entry.created_at}`}
              className={`rounded-xl border p-5 ${LEVEL_STYLES[entry.level] || LEVEL_STYLES.info}`}
            >
              <div className="flex items-center justify-between gap-3 text-[10px] uppercase tracking-wide opacity-80">
                <span>{entry.stage.replaceAll("_", " ")}</span>
                <span>{new Date(entry.created_at).toLocaleTimeString("zh-CN", { hour12: false })}</span>
              </div>
              <p className="mt-1 text-xs leading-5">{entry.message}</p>
            </div>
          ))
        ) : (
          <div className="h-full flex items-center justify-center text-center px-6">
            <span className="text-[var(--text-muted)] text-xs italic">
              {selectedNode
                ? "该节点还没有可展示的过程说明。"
                : "工作流开始后，这里会展示每个节点的执行过程说明。"}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
