import { motion } from "framer-motion";
import { TrendingUp, TrendingDown, Lightbulb, AlertTriangle } from "lucide-react";
import type { SWOTAnalysis } from "@/types/artifact";

interface Props {
  swot: SWOTAnalysis;
}

const ITEMS = [
  { key: "strengths" as const, label: "Strengths", sub: "核心竞争优势", color: "emerald", Icon: TrendingUp },
  { key: "weaknesses" as const, label: "Weaknesses", sub: "潜在风险劣势", color: "rose", Icon: TrendingDown },
  { key: "opportunities" as const, label: "Opportunities", sub: "市场卡位机遇", color: "blue", Icon: Lightbulb },
  { key: "threats" as const, label: "Threats", sub: "外部竞争威胁", color: "amber", Icon: AlertTriangle },
];

const COLORS: Record<string, { bg: string; border: string; iconBg: string; iconColor: string }> = {
  emerald: { bg: "bg-emerald-500/5", border: "border-emerald-500/20", iconBg: "bg-emerald-500/10", iconColor: "text-emerald-400" },
  rose: { bg: "bg-rose-500/5", border: "border-rose-500/20", iconBg: "bg-rose-500/10", iconColor: "text-rose-400" },
  blue: { bg: "bg-blue-500/5", border: "border-blue-500/20", iconBg: "bg-blue-500/10", iconColor: "text-blue-400" },
  amber: { bg: "bg-amber-500/5", border: "border-amber-500/20", iconBg: "bg-amber-500/10", iconColor: "text-amber-400" },
};

export function SwotGrid({ swot }: Props) {
  return (
    <div className="grid grid-cols-2 gap-4">
      {ITEMS.map(({ key, label, sub, color, Icon }, i) => {
        const c = COLORS[color];
        return (
          <motion.div
            key={key}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.08 }}
            className={`rounded-2xl border ${c.border} ${c.bg} p-5`}
          >
            <div className="flex items-center gap-2 mb-3">
              <div className={`w-8 h-8 rounded-lg ${c.iconBg} flex items-center justify-center`}>
                <Icon size={16} className={c.iconColor} />
              </div>
              <div>
                <p className="text-sm font-semibold text-[var(--text-primary)]">{label}</p>
                <p className="text-[11px] text-[var(--text-muted)]">{sub}</p>
              </div>
            </div>
            <ul className="space-y-1.5">
              {(swot[key] ?? []).map((item, j) => (
                <li key={j} className="text-xs text-[var(--text-secondary)] leading-relaxed pl-1">
                  {item}
                </li>
              ))}
            </ul>
          </motion.div>
        );
      })}
    </div>
  );
}
