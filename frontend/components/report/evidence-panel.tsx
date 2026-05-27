"use client";

import { motion, AnimatePresence } from "framer-motion";
import { X, ExternalLink, ShieldCheck, ShieldAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { Citation } from "@/types/artifact";
import type { TraceLink } from "@/types/trace";

interface Props {
  citations: Citation[];
  traceLinks: TraceLink[];
  activeCitationIndex: number | null;
  onClose: () => void;
}

export function EvidencePanel({ citations, traceLinks, activeCitationIndex, onClose }: Props) {
  const activeCitation = citations.find((c) => c.index === activeCitationIndex);
  const relatedTraces = traceLinks.filter((t) => activeCitation && t.source_url === activeCitation.url);

  return (
    <AnimatePresence>
      {activeCitationIndex !== null && (
        <motion.aside
          initial={{ x: 320 }}
          animate={{ x: 0 }}
          exit={{ x: 320 }}
          transition={{ type: "spring", damping: 25, stiffness: 300 }}
          className="fixed right-0 top-0 h-full w-80 border-l border-[var(--border)] bg-[var(--bg-card)] z-20 shadow-2xl overflow-y-auto"
        >
          <div className="p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">证据溯源</h3>
              <button onClick={onClose} className="p-1 rounded-md text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)]">
                <X size={16} />
              </button>
            </div>

            {activeCitation ? (
              <div className="space-y-4">
                <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-elevated)] p-4">
                  <p className="text-xs text-[var(--text-muted)] mb-1">来源 #{activeCitation.index}</p>
                  <p className="text-sm font-medium text-[var(--text-primary)]">{activeCitation.title}</p>
                  <a href={activeCitation.url} target="_blank" rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-xs text-emerald-500 hover:underline mt-2">
                    <ExternalLink size={10} /> 查看原文
                  </a>
                  <p className="text-[11px] text-[var(--text-muted)] mt-1">访问日期: {activeCitation.access_date}</p>
                </div>

                {relatedTraces.map((trace) => (
                  <div key={trace.id} className="rounded-xl border border-[var(--border)] p-3">
                    <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{trace.claim}</p>
                    <div className="flex items-center gap-2 mt-2">
                      {trace.is_verified ? (
                        <Badge variant="success" className="gap-1 text-[10px]"><ShieldCheck size={10} /> 已验证</Badge>
                      ) : (
                        <Badge variant="warning" className="gap-1 text-[10px]"><ShieldAlert size={10} /> 未验证</Badge>
                      )}
                      <span className="text-[10px] text-[var(--text-muted)]">置信度 {Math.round(trace.confidence * 100)}%</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-xs text-[var(--text-muted)] p-4 rounded-xl border border-[var(--border)]">
                <p>共 {citations.length} 个引用 · {traceLinks.length} 条溯源</p>
              </div>
            )}
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
