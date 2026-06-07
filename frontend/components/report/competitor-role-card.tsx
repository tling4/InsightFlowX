"use client";

import type { CompetitorRoleAnalysis } from "@/types/artifact";

const ROLE_LABELS: Record<CompetitorRoleAnalysis["items"][number]["role"], string> = {
  core: "核心竞品",
  benchmark: "标杆竞品",
  potential: "潜力竞品",
  substitute: "替代竞品",
  pitfall: "避坑竞品",
  unknown: "待确认角色",
};

interface Props {
  data: CompetitorRoleAnalysis;
}

export function CompetitorRoleCard({ data }: Props) {
  if (!data?.items?.length) return null;

  return (
    <section className="rounded-2xl border border-[var(--border)] bg-[var(--bg-card)]/80 p-5 space-y-4">
      <div className="space-y-1">
        <h3 className="text-base font-semibold text-[var(--text-primary)]">竞品角色判断</h3>
        <p className="text-sm text-[var(--text-muted)]">
          在报告生成前，先确认系统如何理解这些竞品在当前细分市场中的角色。
        </p>
      </div>

      <div className="grid gap-3">
        {data.items.map((item) => (
          <div
            key={item.product}
            className="rounded-xl border border-[var(--border)] bg-[var(--bg-elevated)]/70 p-4 space-y-2"
          >
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-medium text-[var(--text-primary)]">{item.product}</div>
              <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-xs text-emerald-300">
                {ROLE_LABELS[item.role]}
              </span>
            </div>
            <p className="text-sm leading-6 text-[var(--text-secondary)]">{item.reason}</p>
          </div>
        ))}
      </div>

      {data.summary && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-elevated)]/50 p-4">
          <div className="text-xs uppercase tracking-wide text-[var(--text-muted)] mb-2">总结</div>
          <p className="text-sm leading-6 text-[var(--text-secondary)]">{data.summary}</p>
        </div>
      )}
    </section>
  );
}
