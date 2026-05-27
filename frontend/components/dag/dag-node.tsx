"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "reactflow";
import { motion } from "framer-motion";
import { CheckCircle2, Loader2, AlertCircle, RefreshCw } from "lucide-react";
import { cn } from "@/lib/cn";
import { formatDuration } from "@/lib/utils";
import type { NodeStatus } from "./dag-canvas";

interface DagNodeData {
  label: string;
  status: NodeStatus;
  message?: string;
  duration_ms?: number;
  onRetry?: () => void;
}

const STATUS_COLORS: Record<NodeStatus, { bg: string; border: string; text: string; icon: string }> = {
  idle: { bg: "bg-[var(--bg-card)]", border: "border-[var(--border)]", text: "text-[var(--text-muted)]", icon: "text-zinc-600" },
  active: { bg: "bg-blue-500/5", border: "border-blue-500/50", text: "text-blue-300", icon: "text-blue-400" },
  completed: { bg: "bg-emerald-500/5", border: "border-emerald-500/40", text: "text-emerald-300", icon: "text-emerald-400" },
  failed: { bg: "bg-rose-500/5", border: "border-rose-500/40", text: "text-rose-300", icon: "text-rose-400" },
  rerouted: { bg: "bg-amber-500/5", border: "border-amber-500/40", text: "text-amber-300", icon: "text-amber-400" },
};

function DagNodeComponent({ data }: NodeProps<DagNodeData>) {
  const { label, status, message, duration_ms, onRetry } = data;
  const s = STATUS_COLORS[status];

  return (
    <motion.div
      animate={status === "active" ? { boxShadow: ["0 0 8px rgba(59,130,246,0.3)", "0 0 24px rgba(59,130,246,0.6)", "0 0 8px rgba(59,130,246,0.3)"] } : {}}
      transition={{ duration: 2, repeat: Infinity }}
      className={cn(
        "min-w-[200px] rounded-2xl border-2 px-4 py-3 transition-colors duration-500",
        s.bg, s.border,
        status === "active" && "animate-pulse"
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-[var(--border)]" />
      <div className="flex items-start gap-3">
        <div className="mt-0.5">
          {status === "active" && <Loader2 className={`h-5 w-5 animate-spin ${s.icon}`} />}
          {status === "completed" && <CheckCircle2 className={`h-5 w-5 ${s.icon}`} />}
          {status === "failed" && <AlertCircle className={`h-5 w-5 ${s.icon}`} />}
          {status === "rerouted" && <RefreshCw className={`h-5 w-5 animate-spin ${s.icon}`} />}
          {status === "idle" && <div className="h-5 w-5 rounded-full border-2 border-[var(--border)]" />}
        </div>
        <div className="flex-1 min-w-0">
          <p className={cn("text-sm font-medium whitespace-pre-line", s.text)}>{label}</p>
          {message && <p className="text-xs text-[var(--text-muted)] mt-1 font-mono truncate max-w-[180px]">{message}</p>}
          {duration_ms != null && status === "completed" && (
            <p className="text-xs text-emerald-500 mt-0.5 font-mono">{formatDuration(duration_ms)}</p>
          )}
        </div>
        {status === "failed" && onRetry && (
          <button onClick={(e) => { e.stopPropagation(); onRetry(); }}
            className="text-xs px-2 py-1 rounded-lg bg-rose-500/10 text-rose-400 hover:bg-rose-500/20 border border-rose-500/20">重试</button>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-[var(--border)]" />
    </motion.div>
  );
}

export const DagNode = memo(DagNodeComponent);
