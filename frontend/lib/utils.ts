import type { WorkflowStatus } from "@/types/workflow";

export function statusLabel(status: WorkflowStatus): string {
  const map: Record<WorkflowStatus, string> = {
    created: "已创建",
    configuring: "配置中",
    running: "运行中",
    completed: "已完成",
    failed: "已失败",
    cancelled: "已取消",
  };
  return map[status] || status;
}

export function statusColor(status: WorkflowStatus): string {
  const map: Record<WorkflowStatus, string> = {
    created: "bg-zinc-500/10 text-zinc-400 border-zinc-500/20",
    configuring: "bg-blue-500/10 text-blue-400 border-blue-500/20",
    running: "bg-indigo-500/10 text-indigo-400 border-indigo-500/20",
    completed: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
    failed: "bg-rose-500/10 text-rose-400 border-rose-500/20",
    cancelled: "bg-zinc-500/10 text-zinc-400 border-zinc-500/20",
  };
  return map[status] || "";
}

export function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
}
