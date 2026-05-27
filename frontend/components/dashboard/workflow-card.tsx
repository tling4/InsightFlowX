"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { Spinner } from "@/components/ui/spinner";
import { formatTime, statusLabel } from "@/lib/utils";
import { useDeleteWorkflow } from "@/lib/use-workflow";
import { XCircle } from "lucide-react";
import type { WorkflowListItem } from "@/types/api";

interface Props {
  workflow: WorkflowListItem;
}

export function WorkflowCard({ workflow }: Props) {
  const router = useRouter();
  const deleteMutation = useDeleteWorkflow();
  const [showConfirm, setShowConfirm] = useState(false);

  const handleDelete = async () => {
    await deleteMutation.mutateAsync(workflow.id);
    setShowConfirm(false);
  };

  const isRunning = workflow.status === "running";

  return (
    <>
      <div
        onClick={() => router.push(`/workflows/${workflow.id}`)}
        className="group cursor-pointer rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-5 transition-all duration-300 hover:-translate-y-1 hover:border-emerald-500/30"
        style={{ boxShadow: "var(--card-shadow)" }}
        onMouseEnter={(e) => { e.currentTarget.style.boxShadow = "var(--card-shadow-hover)"; }}
        onMouseLeave={(e) => { e.currentTarget.style.boxShadow = "var(--card-shadow)"; }}
      >
        <div className="flex items-start justify-between mb-3">
          <div className="flex-1 min-w-0">
            <h3 className="text-sm font-semibold text-[var(--text-primary)] truncate">
              {workflow.title}
            </h3>
            <p className="text-xs text-[var(--text-muted)] mt-1">
              {formatTime(workflow.created_at)}
            </p>
          </div>
          <button
            onClick={(e) => { e.stopPropagation(); setShowConfirm(true); }}
            className="shrink-0 ml-2 p-1 rounded-md text-[var(--text-muted)] hover:text-rose-400 hover:bg-rose-500/10 opacity-0 group-hover:opacity-100 transition-all"
          >
            <XCircle size={13} />
          </button>
        </div>

        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            {isRunning && (
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            )}
            <span
              className={`relative inline-flex rounded-full h-2 w-2 ${
                isRunning ? "bg-emerald-400" :
                workflow.status === "completed" ? "bg-emerald-500" :
                workflow.status === "failed" ? "bg-rose-500" :
                "bg-zinc-500"
              }`}
            />
          </span>
          <span className={`text-xs font-medium ${
            isRunning ? "text-emerald-400" :
            workflow.status === "completed" ? "text-emerald-500" :
            "text-[var(--text-secondary)]"
          }`}>
            {statusLabel(workflow.status)}
          </span>
          {workflow.status === "running" && (
            <span className="text-xs text-[var(--text-muted)] ml-auto">
              {workflow.current_phase}
            </span>
          )}
        </div>
      </div>

      <Modal open={showConfirm} onClose={() => setShowConfirm(false)} title="确认删除">
        <div className="space-y-4">
          <p className="text-sm text-[var(--text-secondary)]">
            确定要删除 <span className="text-[var(--text-primary)] font-medium">「{workflow.title}」</span>？
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setShowConfirm(false)}>取消</Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleteMutation.isPending}>
              {deleteMutation.isPending ? <Spinner size={14} /> : <XCircle size={14} />}
              删除
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
}
