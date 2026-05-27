"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { useWorkflows } from "@/lib/use-workflow";
import { AuthGuard } from "@/components/auth/auth-guard";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { WorkflowCard } from "@/components/dashboard/workflow-card";
import { BentoGrid } from "@/components/dashboard/bento-grid";
import { CreateWorkflowDialog } from "@/components/dashboard/create-workflow-dialog";
import { EmptyState } from "@/components/shared/empty-state";
import { Plus, LogOut, Sparkles } from "lucide-react";
import type { WorkflowStatus } from "@/types/workflow";

const STATUS_FILTERS: Array<{ label: string; value: WorkflowStatus | "all" }> = [
  { label: "全部", value: "all" },
  { label: "运行中", value: "running" },
  { label: "配置中", value: "configuring" },
  { label: "已完成", value: "completed" },
  { label: "失败", value: "failed" },
];

export default function DashboardPage() {
  const { user, logout } = useAuth();
  const { data: workflows, isLoading } = useWorkflows();
  const [statusFilter, setStatusFilter] = useState<WorkflowStatus | "all">("all");
  const [showCreate, setShowCreate] = useState(false);

  const filtered = (workflows ?? []).filter(
    (w) => statusFilter === "all" || w.status === statusFilter
  );

  return (
    <AuthGuard>
      <div className="min-h-screen" style={{ backgroundColor: "var(--bg-primary)" }}>
        <header className="sticky top-0 z-10 border-b border-[var(--border)] bg-[var(--bg-primary)]/80 backdrop-blur-xl">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
                <Sparkles size={16} className="text-emerald-400" />
              </div>
              <div>
                <h1 className="text-sm font-bold text-[var(--text-primary)]">DAGents InsightFlow</h1>
                {user && <p className="text-xs text-[var(--text-muted)]">{user.username}</p>}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button
                onClick={() => setShowCreate(true)}
                className="bg-emerald-500 hover:bg-emerald-600 text-white rounded-xl text-xs gap-1.5 shadow-[0_0_16px_var(--accent-glow)]"
                size="sm"
              >
                <Plus size={14} /> 新建分析
              </Button>
              <button onClick={logout} className="p-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-elevated)] transition-colors">
                <LogOut size={14} />
              </button>
            </div>
          </div>
        </header>

        <main className="mx-auto max-w-6xl px-6 py-8">
          <div className="mb-6 flex items-center gap-1">
            {STATUS_FILTERS.map((f) => (
              <button
                key={f.value}
                onClick={() => setStatusFilter(f.value)}
                className={`px-3 py-1.5 text-xs rounded-lg transition-all ${
                  statusFilter === f.value
                    ? "bg-[var(--bg-elevated)] text-[var(--text-primary)] font-medium"
                    : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>

          {isLoading ? (
            <div className="flex justify-center py-20">
              <Spinner size={24} />
            </div>
          ) : filtered.length === 0 ? (
            <EmptyState
              title={statusFilter === "all" ? "还没有分析项目" : "没有匹配的工作流"}
              description="创建第一个竞品分析任务，启动 AI Agent 协作流程"
              action={
                <Button onClick={() => setShowCreate(true)} className="bg-emerald-500 hover:bg-emerald-600 text-white rounded-xl shadow-[0_0_16px_var(--accent-glow)]">
                  <Plus size={14} /> 新建分析
                </Button>
              }
            />
          ) : (
            <BentoGrid>
              {filtered.map((w) => (
                <WorkflowCard key={w.id} workflow={w} />
              ))}
            </BentoGrid>
          )}
        </main>

        <CreateWorkflowDialog open={showCreate} onClose={() => setShowCreate(false)} />
      </div>
    </AuthGuard>
  );
}
