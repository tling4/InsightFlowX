"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useParams } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth-context";
import { useWorkflow, useStartWorkflow } from "@/lib/use-workflow";
import { useInterviewHistory } from "@/lib/use-interview";
import { useArtifacts } from "@/lib/use-artifacts";
import { useTraceLinks } from "@/lib/use-trace";
import { useInterviewStream } from "@/lib/use-interview-stream";
import { useWorkflowStream } from "@/lib/use-workflow-stream";
import { useNodeStream } from "@/lib/use-node-stream";
import { AuthGuard } from "@/components/auth/auth-guard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { ChatStream } from "@/components/interview/chat-stream";
import { ConfigPanel } from "@/components/interview/config-panel";
import { DagCanvas } from "@/components/dag/dag-canvas";
import type { NodeStatus } from "@/components/dag/dag-canvas";
import { StreamPanel } from "@/components/events/stream-panel";
import { EventConsole } from "@/components/events/event-console";
import { ReportViewer } from "@/components/report/report-viewer";
import { OutlineNav } from "@/components/report/outline-nav";
import { EvidencePanel } from "@/components/report/evidence-panel";
import { SwotGrid } from "@/components/report/swot-grid";
import { FeatureMatrixTable } from "@/components/report/feature-matrix-table";
import { PricingTable } from "@/components/report/pricing-table";
import { SentimentPanel } from "@/components/report/sentiment-panel";
import { CompetitorRoleCard } from "@/components/report/competitor-role-card";
import { RevisionTimeline } from "@/components/report/revision-timeline";
import { Send, ArrowLeft, Layers, FileText, Sparkles, Pencil, MessageSquare, Network, Download, Printer } from "lucide-react";
import Link from "next/link";
import { statusLabel, statusColor } from "@/lib/utils";
import type { InterviewMessage } from "@/types/interview";
import type { CompetitorGroups, WorkflowConfig, WorkflowDetail } from "@/types/workflow";
import type { WorkflowEvent, AgentNodeName } from "@/types/event";
import { AGENT_NODE_ORDER } from "@/types/event";
import type { ReportOutput, SWOTAnalysis, FeatureMatrix, PricingComparison, UserSentimentAnalysis, CompetitorRoleAnalysis } from "@/types/artifact";

const SHOW_DEBUG_EVENTS = process.env.NEXT_PUBLIC_ENABLE_DEBUG_EVENTS === "true";

export default function WorkflowStudioPage() {
  const { id } = useParams<{ id: string }>();
  const { token } = useAuth();
  const qc = useQueryClient();
  const { data: workflow, isLoading } = useWorkflow(id);
  const status = workflow?.status;
  const [titleOverride, setTitleOverride] = useState<string | null>(null);
  const displayTitle = titleOverride ?? workflow?.title ?? "未命名分析";

  if (isLoading) {
    return (
      <AuthGuard>
        <div className="flex h-screen items-center justify-center" style={{ backgroundColor: "var(--bg-primary)" }}>
          <Spinner size={24} />
        </div>
      </AuthGuard>
    );
  }

  // 加载完成但未获取到 workflow（404 / 无权限）
  if (!workflow) {
    return (
      <AuthGuard>
        <div className="flex h-screen items-center justify-center" style={{ backgroundColor: "var(--bg-primary)" }}>
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-6 py-4 text-center max-w-md">
            <p className="text-sm text-rose-300">工作流不存在或无访问权限</p>
            <Link href="/dashboard" className="mt-3 inline-block text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] underline">
              返回仪表板
            </Link>
          </div>
        </div>
      </AuthGuard>
    );
  }

  // 状态路由：created 视为 configuring 入口；未知 status 渲染 fallback
  const isInterviewStage = status === "configuring" || status === "created";
  const isRuntimeStage = status === "running" || status === "paused";
  const isTerminalStage = status === "completed" || status === "failed" || status === "cancelled";

  return (
    <AuthGuard>
      <div className="min-h-screen" style={{ backgroundColor: "var(--bg-primary)" }}>
        <Header workflow={workflow} displayTitle={displayTitle} onTitleChange={(newTitle) => {
          setTitleOverride(newTitle);
          qc.setQueryData<WorkflowDetail | undefined>(["workflow", id], (old) =>
            old ? { ...old, title: newTitle } : old
          );
          qc.invalidateQueries({ queryKey: ["workflows"] });
          const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
          fetch(`${baseUrl}/workflows/${id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
            body: JSON.stringify({ title: newTitle }),
          }).catch(() => {});
        }} />
        {isInterviewStage && <div className="h-[calc(100vh-57px)]"><InterviewView workflowId={id} token={token!} workflow={workflow} /></div>}
        {isRuntimeStage && <div className="h-[calc(100vh-57px)]"><DagRuntimeView workflowId={id} token={token!} workflow={workflow} /></div>}
        {isTerminalStage && <TerminalTabs workflowId={id} token={token!} workflow={workflow} />}
        {!isInterviewStage && !isRuntimeStage && !isTerminalStage && (
          <div className="flex h-[calc(100vh-57px)] items-center justify-center">
            <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-6 py-4 text-center max-w-md space-y-3">
              <p className="text-sm text-amber-300">无法识别的工作流状态: <code className="bg-black/30 px-1 rounded">{String(status)}</code></p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => qc.invalidateQueries({ queryKey: ["workflow", id] })}
                className="text-xs"
              >
                刷新状态
              </Button>
            </div>
          </div>
        )}
      </div>
    </AuthGuard>
  );
}

function Header({ workflow, displayTitle, onTitleChange }: { workflow: { id?: string; title?: string; status?: string; current_phase?: string; revision_count?: number } | undefined; displayTitle?: string; onTitleChange?: (title: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState(displayTitle || workflow?.title || "未命名分析");
  const title = displayTitle || workflow?.title || "未命名分析";

  useEffect(() => {
    if (!editing) setDraftTitle(displayTitle || workflow?.title || "未命名分析");
  }, [displayTitle, workflow?.title, editing]);

  const save = () => {
    const trimmed = draftTitle.trim();
    if (trimmed && trimmed !== workflow?.title) {
      onTitleChange?.(trimmed);
    }
    setEditing(false);
  };

  return (
    <header className="border-b border-[var(--border)] bg-[var(--bg-primary)]/80 backdrop-blur-xl sticky top-0 z-10">
      <div className="flex items-center justify-between px-6 py-3">
        <div className="flex items-center gap-3">
          <Link href="/dashboard" className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors">
            <ArrowLeft size={18} />
          </Link>
          {editing ? (
            <input
              value={draftTitle}
              onChange={(e) => setDraftTitle(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") save(); if (e.key === "Escape") setEditing(false); }}
              onBlur={save}
              autoFocus
              className="text-lg font-bold text-[var(--text-primary)] bg-transparent border-b border-emerald-500/50 outline-none px-1"
            />
          ) : (
            <div className="flex items-center gap-2 group cursor-pointer" onClick={() => setEditing(true)} onDoubleClick={() => setEditing(true)}>
              <h1 className="text-lg font-bold text-[var(--text-primary)]">{title}</h1>
              <Pencil size={12} className="text-[var(--text-muted)]" />
            </div>
          )}
          {workflow?.status && (
            <Badge className={statusColor(workflow.status as Parameters<typeof statusColor>[0]) || ""}>
              {statusLabel(workflow.status as Parameters<typeof statusLabel>[0]) || workflow.status}
            </Badge>
          )}
        </div>
        <div className="text-xs text-[var(--text-muted)]">
          {workflow?.revision_count != null && `Revision ${workflow.revision_count}`}
        </div>
      </div>
    </header>
  );
}

/* ─── Interview View ─── */
const QUICK_CARDS = [
  { title: "分析一个产品的主要竞品", content: "例如：分析抖音的主要竞品" },
  { title: "对比多个竞品", content: "例如：抖音、快手、小红书对比分析" },
  { title: "发现市场机会", content: "例如：短视频赛道还有哪些空白机会" },
];

function InterviewView({ workflowId, token, workflow }: { workflowId: string; token: string; workflow: WorkflowDetail }) {
  const [config, setConfig] = useState<Partial<WorkflowConfig>>(() => {
    const sc = workflow.config as Partial<WorkflowConfig> | undefined;
    return sc && Object.keys(sc).length > 0 ? { ...sc } : {};
  });
  const [isComplete, setIsComplete] = useState<boolean>(() => {
    const sc = workflow.config as Partial<WorkflowConfig> | undefined;
    return Boolean(sc?.target_product && sc?.product_category);
  });
  const [messages, setMessages] = useState<InterviewMessage[]>(() => {
    // 从 React Query 缓存初始化，避免终端状态下 ChatStream 空态闪烁
    try {
      const cached = qc.getQueryData<InterviewMessage[]>(["interview-history", workflowId]);
      return cached ?? [];
    } catch { return []; }
  });
  const [inputValue, setInputValue] = useState("");
  const [newCompetitor, setNewCompetitor] = useState("");
  const [startError, setStartError] = useState<string | null>(null);
  const qc = useQueryClient();
  const { sendMessage, isStreaming } = useInterviewStream({ workflowId, token });
  const startMutation = useStartWorkflow();
  const { data: history, isLoading: historyLoading, isPending: historyPending } = useInterviewHistory(workflowId);
  const isTerminalView = workflow.status === "completed" || workflow.status === "failed" || workflow.status === "cancelled";

  // 终端状态的工作流始终视为有消息，避免闪回首页欢迎界面
  const hasMessages = isTerminalView || (!historyPending && (messages.length > 0 || (!!history && history.length > 0)));

  // ChatStream 展示用消息：优先用 messages state（含流式增量），回退到 history（终端态下 useEffect 尚未触发时）
  const displayMessages: InterviewMessage[] = messages.length > 0 ? messages : (history ?? []);

  useEffect(() => {
    if (history && history.length > 0) {
      setMessages(history);
    }
  }, [history]);

  const canStart = Boolean(config.target_product && config.product_category);

  const normalizeNames = useCallback((names: string[]) => {
    const seen = new Set<string>();
    return names.map((name) => name.trim()).filter((name) => {
      const lowered = name.toLowerCase();
      if (!name || seen.has(lowered)) return false;
      seen.add(lowered);
      return true;
    });
  }, []);

  const flattenGroups = useCallback((groups?: Partial<CompetitorGroups> | null) => {
    if (!groups) return [];
    return normalizeNames([
      ...(groups.core ?? []),
      ...(groups.benchmark ?? []),
      ...(groups.potential ?? []),
      ...(groups.substitute ?? []),
      ...(groups.pitfall ?? []),
    ]);
  }, [normalizeNames]);

  const assignToGroups = useCallback((names: string[], existing?: Partial<CompetitorGroups> | null): CompetitorGroups => {
    const groups: CompetitorGroups = {
      core: [...(existing?.core ?? [])],
      benchmark: [...(existing?.benchmark ?? [])],
      potential: [...(existing?.potential ?? [])],
      substitute: [...(existing?.substitute ?? [])],
      pitfall: [...(existing?.pitfall ?? [])],
    };
    const used = new Set(flattenGroups(groups).map((name) => name.toLowerCase()));
    for (const name of normalizeNames(names)) {
      if (used.has(name.toLowerCase())) continue;
      groups.core.push(name);
      used.add(name.toLowerCase());
    }
    return groups;
  }, [flattenGroups, normalizeNames]);

  const sendUserMessage = (text: string) => {
    if (!text.trim() || isStreaming) return;
    const userMsg: InterviewMessage = { role: "user", content: text, created_at: new Date().toISOString() };
    setMessages((prev) => [...prev, userMsg, { role: "assistant", content: "", created_at: new Date().toISOString() }]);
    setInputValue("");

    sendMessage(
      userMsg.content,
      (tokenStr) => {
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last && last.role === "assistant") {
            updated[updated.length - 1] = { ...last, content: last.content + tokenStr };
          }
          return updated;
        });
      },
      (incoming) => {
        if (incoming.extracted_config) {
          setConfig((prev) => {
            const merged = { ...prev, ...incoming.extracted_config };
            const groups = assignToGroups(
              merged.competitors ?? [],
              incoming.extracted_config?.competitor_groups ?? merged.competitor_groups,
            );
            return { ...merged, competitor_groups: groups, competitors: flattenGroups(groups) };
          });
        }
        const competitors = incoming.suggested_competitors;
        if (competitors && competitors.length > 0) {
          setConfig((prev) => {
            const groups = assignToGroups(competitors, incoming.suggested_competitor_groups ?? prev.competitor_groups);
            return { ...prev, competitor_groups: groups, competitors: flattenGroups(groups) };
          });
        }
      },
      () => { setIsComplete(true); },
      (err) => {
        console.error("Interview SSE error:", err);
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          const errorText = `回复失败：${err.message}`;
          if (last?.role === "assistant" && !last.content) {
            updated[updated.length - 1] = { ...last, content: errorText };
          } else {
            updated.push({ role: "assistant", content: errorText, created_at: new Date().toISOString() });
          }
          return updated;
        });
      }
    );
  };

  const handleSend = () => sendUserMessage(inputValue);
  const handleQuickReply = (text: string) => sendUserMessage(text);
  const handleResumeEditing = () => { setIsComplete(false); setStartError(null); };

  const handleStart = async () => {
    setStartError(null);
    if (!canStart) { setStartError("配置不完整：target_product 和 product_category 必填"); return; }
    try {
      await startMutation.mutateAsync({ id: workflowId, config });
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string; message?: string } } })?.response?.data?.detail
        || (err as { response?: { data?: { detail?: string; message?: string } } })?.response?.data?.message
        || (err as Error).message || "启动失败";
      setStartError(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
  };

  const clearStartError = () => { if (startError) setStartError(null); };

  useEffect(() => {
    if (!isComplete || canStart) return;
    const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
    fetch(`${baseUrl}/workflows/${workflowId}`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.json())
      .then((data) => { if (data?.config) setConfig((prev) => ({ ...data.config, ...prev })); })
      .catch(() => {});
  }, [isComplete, canStart, workflowId, token]);

  return (
    <div className="flex h-full" style={{ backgroundColor: "var(--bg-primary)" }}>
      {/* ── Left: Chat Area ── */}
      <div className="flex flex-col w-[65%] border-r border-[var(--border)]" style={{ backgroundColor: "var(--bg-primary)" }}>
        {!hasMessages && !historyLoading && !historyPending ? (
          /* ── INIT: Welcome ── */
          <div className="flex-1 flex flex-col items-center justify-center px-6 overflow-y-auto">
            <div className="max-w-lg w-full space-y-6 text-center">
              <Sparkles size={36} className="mx-auto text-emerald-400" />
              <div>
                <h2 className="text-xl md:text-2xl font-semibold bg-gradient-to-r from-blue-600 to-indigo-600 bg-clip-text text-transparent">
                  开始一次竞品分析
                </h2>
                <p className="text-sm text-slate-500 mt-2 leading-relaxed">
                  通过自然对话描述你的分析需求，AI 将自动配置分析流程并同步更新右侧看板。
                </p>
              </div>
              <div className="grid grid-cols-1 gap-3 w-full">
                {QUICK_CARDS.map((card, i) => (
                  <button
                    key={i}
                    onClick={() => sendUserMessage(card.title)}
                    className="text-left rounded-2xl border border-slate-200 dark:border-zinc-700/50 bg-white dark:bg-zinc-900/50 shadow-sm hover:-translate-y-0.5 hover:border-blue-500/30 hover:bg-blue-50/10 dark:hover:bg-blue-500/5 transition-all cursor-pointer p-4"
                  >
                    <p className="text-sm font-medium text-slate-800 dark:text-zinc-200">{card.title}</p>
                    <p className="text-xs text-slate-500 mt-1">{card.content}</p>
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (historyLoading || historyPending) && displayMessages.length === 0 ? (
          /* ── LOADING ── */
          <div className="flex-1 flex items-center justify-center">
            <Spinner size={20} />
          </div>
        ) : (
          /* ── ACTIVE: Chat Stream ── */
          <ChatStream messages={displayMessages} isStreaming={isStreaming} onQuickReply={handleQuickReply} />
        )}

        {/* ── Chat Input Bar ── */}
        <div className="p-4 border-t border-[var(--border)]">
          <div className="flex gap-2 max-w-4xl mx-auto">
            <textarea
              value={inputValue}
              onChange={(e) => {
                setInputValue(e.target.value);
                e.target.style.height = "auto";
                e.target.style.height = Math.min(e.target.scrollHeight, 192) + "px";
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
              }}
              placeholder={isStreaming ? "AI 正在回复中..." : "输入想分析的产品、竞品范围，或直接点击上方推荐场景..."}
              disabled={isStreaming}
              rows={1}
              className="flex-1 resize-none rounded-2xl border border-slate-200 dark:border-zinc-700 bg-white dark:bg-zinc-900/50 px-4 py-2.5 text-sm text-slate-800 dark:text-zinc-200 placeholder:text-slate-400 dark:placeholder:text-zinc-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40 focus-visible:border-blue-500/40 disabled:opacity-50 shadow-sm transition-all"
            />
            <Button onClick={handleSend} disabled={isStreaming || !inputValue.trim()} variant="primary" size="icon" className="rounded-xl">
              <Send size={16} />
            </Button>
          </div>
        </div>
      </div>

      {/* ── Right: Config Panel ── */}
      <div className="w-[35%] p-5 backdrop-blur-xl bg-[var(--bg-primary)]/60 border-l border-[var(--border)]">
        <ConfigPanel
          config={config} isComplete={isComplete} isStarting={startMutation.isPending}
          newCompetitor={newCompetitor} canStart={canStart} startError={startError}
          onNewCompetitorChange={setNewCompetitor}
          onAddCompetitor={() => {
            if (newCompetitor.trim()) {
              setConfig((prev) => {
                const groups = assignToGroups([newCompetitor.trim()], prev.competitor_groups);
                return { ...prev, competitor_groups: groups, competitors: flattenGroups(groups) };
              });
              setNewCompetitor(""); clearStartError();
            }
          }}
          onRemoveCompetitor={(name) => {
            setConfig((prev) => {
              const groups = Object.fromEntries(
                Object.entries(prev.competitor_groups ?? {}).map(([key, values]) => [
                  key,
                  ((values ?? []) as string[]).filter((item: string) => item !== name),
                ]),
              ) as unknown as CompetitorGroups;
              return { ...prev, competitor_groups: groups, competitors: flattenGroups(groups) };
            });
            clearStartError();
          }}
          onConfigChange={(field, value) => {
            setConfig((prev) => field === "competitor_groups"
              ? { ...prev, competitor_groups: value as CompetitorGroups, competitors: flattenGroups(value as CompetitorGroups) }
              : { ...prev, [field]: value });
            clearStartError();
          }}
          onStart={handleStart} onResumeEditing={handleResumeEditing}
        />
      </div>
    </div>
  );
}

/* ─── DAG Runtime View ─── */
function DagRuntimeView({ workflowId, token, workflow }: { workflowId: string; token: string; workflow: WorkflowDetail }) {
  const createEmptyNodeStates = (): Record<AgentNodeName, { status: NodeStatus; message?: string; duration_ms?: number }> =>
    AGENT_NODE_ORDER.reduce((acc, node) => {
      acc[node] = { status: "idle" };
      return acc;
    }, {} as Record<AgentNodeName, { status: NodeStatus; message?: string; duration_ms?: number }>);

  const qc = useQueryClient();
  const isPaused = workflow.status === "paused";
  const executionAttempt = workflow.execution_attempt;
  const [nodeStates, setNodeStates] = useState<
    Record<AgentNodeName, { status: NodeStatus; message?: string; duration_ms?: number }>
  >(createEmptyNodeStates);
  const [hasReroute, setHasReroute] = useState(false);
  const [rerouteTarget, setRerouteTarget] = useState<AgentNodeName>("analysis");
  const { activeNode, selectedNode, entries, appendEvent, rebuildFromEvents, setSelectedNode } = useNodeStream();
  const [debugEvents, setDebugEvents] = useState<WorkflowEvent[]>([]);
  const [dialogInput, setDialogInput] = useState("");
  const [dialogMessages, setDialogMessages] = useState<Array<{ role: "user" | "system"; content: string; time: string }>>([]);
  const [deciding, setDeciding] = useState(false);
  const [decideError, setDecideError] = useState<string | null>(null);
  const [recoveryState, setRecoveryState] = useState<"idle" | "recovering" | "failed">("idle");
  const recoveryTriggeredRef = useRef(false);

  const patchWorkflowCache = useCallback((patch: Partial<WorkflowDetail>) => {
    qc.setQueryData<WorkflowDetail | undefined>(["workflow", workflowId], (current) => {
      if (!current) return current;
      return { ...current, ...patch };
    });
  }, [qc, workflowId]);

  const handleEvent = useCallback((e: WorkflowEvent) => {
    if (SHOW_DEBUG_EVENTS) {
      setDebugEvents((prev) => [...prev.slice(-199), e]);
    }

    if (e.event_type === "node_start" && e.node_name) {
      setRecoveryState("idle");
    }

    if (e.event_type === "workflow_resumed") {
      patchWorkflowCache({ status: "running", pause_state: null });
    }
    if (e.event_type === "workflow_paused") {
      patchWorkflowCache({
        status: "paused",
        pause_state: {
          paused_by_node: String((e as unknown as Record<string, unknown>).paused_by_node || "review"),
          pause_reason: String((e as unknown as Record<string, unknown>).pause_reason || "等待人工决策"),
          pause_options: ((e as unknown as Record<string, unknown>).pause_options as Array<{ value: string; label: string; target_node?: string }>) || [],
          pause_context: ((e as unknown as Record<string, unknown>).pause_context as Record<string, unknown>) || {},
          paused_at: String((e as unknown as Record<string, unknown>).paused_at || new Date().toISOString()),
        },
      });
    }
    if (e.event_type === "workflow_complete") {
      patchWorkflowCache({ status: "completed", pause_state: null });
    }
    if (e.event_type === "workflow_failed") {
      patchWorkflowCache({ status: "failed", pause_state: null });
    }

    const PROCESS_EVENTS = [
      "node_progress",
      "node_start",
      "node_complete",
      "node_error",
      "tool_call",
      "tool_result",
      "llm_response",
      "review_pass",
      "review_fail",
      "review_failed_max_revisions",
      "reroute",
      "workflow_start",
      "workflow_paused",
      "workflow_resumed",
      "workflow_failed",
      "workflow_complete",
    ];
    if (PROCESS_EVENTS.includes(e.event_type)) {
      appendEvent(e);
    }

    // Only node lifecycle events affect nodeStates; skip irrelevant ones
    // to prevent ReactFlow from rebuilding all nodes on every SSE event
    const NODE_EVENTS = ["node_start", "node_complete", "node_error", "reroute"];
    if (!NODE_EVENTS.includes(e.event_type)) return;

    setNodeStates((prev) => {
      const node = e.node_name as AgentNodeName;
      if (!node) return prev;

      const next = { ...prev };
      const payload = e.payload as Record<string, unknown> | undefined;

      switch (e.event_type) {
        case "node_start":
          next[node] = { ...next[node], status: "active", message: "Running..." };
          break;
        case "node_complete":
          next[node] = {
            ...next[node],
            status: "completed",
            message: "Completed",
            duration_ms: (payload?.duration_ms as number) ?? undefined,
          };
          break;
        case "node_error":
          next[node] = { ...next[node], status: "failed", message: (payload?.error_message as string) || "Error" };
          break;
        case "reroute":
          next.review = { ...next.review, status: "rerouted", message: "Rerouting..." };
          if (payload?.to_node || payload?.target_node) {
            const rerouteTarget = (payload?.to_node || payload?.target_node) as AgentNodeName;
            next[rerouteTarget] = { ...next[rerouteTarget], status: "idle" };
          }
          break;
      }
      return next;
    });

    if (e.event_type === "reroute") {
      setHasReroute(true);
      const payload = e.payload as Record<string, unknown> | undefined;
      const target = (payload?.to_node || payload?.target_node) as AgentNodeName | undefined;
      if (target) setRerouteTarget(target);
    }
  }, [appendEvent, patchWorkflowCache]);

  const handleSendDialog = () => {
    const text = dialogInput.trim();
    if (!text) return;
    setDialogMessages((prev) => [...prev, {
      role: "user",
      content: text,
      time: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
    }]);
    setDialogInput("");
  };

  const handleDecide = async (action: string, targetNode?: string, feedback?: string) => {
    setDeciding(true);
    setDecideError(null);
    try {
      const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
      const res = await fetch(`${baseUrl}/workflows/${workflowId}/decide`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          action,
          target_node: targetNode || null,
          feedback: feedback || dialogInput.trim(),
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail || `HTTP ${res.status}`);
      }
      setDialogInput("");
      setDialogMessages((prev) => [...prev, {
        role: "system",
        content: `已提交决策: ${action === "jump" ? `重试 ${targetNode || ""}` : action === "approve" ? "强制通过" : "放弃"}`,
        time: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
      }]);
      if (action === "jump") {
        patchWorkflowCache({ status: "running", pause_state: null });
      } else if (action === "approve") {
        patchWorkflowCache({ status: "completed", pause_state: null });
      } else if (action === "abort") {
        patchWorkflowCache({ status: "cancelled", pause_state: null });
      }
      // 失效 workflow 缓存：approve→completed / abort→cancelled / jump→running 切换不依赖 SSE 到达
      qc.invalidateQueries({ queryKey: ["workflow", workflowId] });
      qc.invalidateQueries({ queryKey: ["workflows"] });
    } catch (err) {
      setDecideError((err as Error).message || "决策提交失败");
    } finally {
      setDeciding(false);
    }
  };

  // Terminal status: just replay historical events (no SSE, no recovery)
  const isTerminal = workflow.status === "completed" || workflow.status === "failed" || workflow.status === "cancelled";
  useEffect(() => {
    if (!isTerminal) return;
    const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
    fetch(`${baseUrl}/workflows/${workflowId}/events?limit=200&execution_attempt=${executionAttempt}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.json())
      .then((body) => {
        const events: WorkflowEvent[] = Array.isArray(body) ? body : (body?.items ?? []);
        if (events.length === 0) return;
        rebuildFromEvents(events);
        const rebuilt = createEmptyNodeStates();
        let hadReroute = false;
        for (const e of [...events].sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0))) {
          const node = e.node_name as AgentNodeName;
          if (!node) continue;
          const p = e.payload as Record<string, unknown> | undefined;
          if (e.event_type === "node_start") rebuilt[node] = { ...rebuilt[node], status: "active", message: "Running..." };
          else if (e.event_type === "node_complete") rebuilt[node] = { ...rebuilt[node], status: "completed", message: "Completed", duration_ms: (p?.duration_ms as number) ?? undefined };
          else if (e.event_type === "node_error") rebuilt[node] = { ...rebuilt[node], status: "failed", message: (p?.error_message as string) || "Error" };
          else if (e.event_type === "reroute") { rebuilt.review = { ...rebuilt.review, status: "rerouted", message: "Rerouting..." }; hadReroute = true; }
        }
        setNodeStates(rebuilt);
        setHasReroute(hadReroute);
      })
      .catch(() => {});
  }, [workflowId, token, executionAttempt, isTerminal, rebuildFromEvents]);

  // Replay current-attempt history on mount, then recover if the workflow is stale.
  useEffect(() => {
    recoveryTriggeredRef.current = false;
    queueMicrotask(() => setRecoveryState("idle"));

    const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";

    const rebuildNodeStatesFromEvents = (list: WorkflowEvent[]) => {
      const rebuilt = createEmptyNodeStates();
      let reroute = false;
      let lastEventTime = 0;
      let hasLifecycleEvents = false;

      for (const e of [...list].sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0))) {
        const node = e.node_name as AgentNodeName;
        if (!node) continue;
        const payload = e.payload as Record<string, unknown> | undefined;
        switch (e.event_type) {
          case "node_start":
            rebuilt[node] = { ...rebuilt[node], status: "active", message: "Running..." };
            hasLifecycleEvents = true;
            break;
          case "node_complete":
            rebuilt[node] = {
              ...rebuilt[node],
              status: "completed",
              message: "Completed",
              duration_ms: (payload?.duration_ms as number) ?? undefined,
            };
            hasLifecycleEvents = true;
            break;
          case "node_error":
            rebuilt[node] = { ...rebuilt[node], status: "failed", message: (payload?.error_message as string) || "Error" };
            hasLifecycleEvents = true;
            break;
          case "reroute":
            rebuilt.review = { ...rebuilt.review, status: "rerouted", message: "Rerouting..." };
            if (payload?.to_node || payload?.target_node) {
              const rerouteTarget = (payload?.to_node || payload?.target_node) as AgentNodeName;
              rebuilt[rerouteTarget] = { ...rebuilt[rerouteTarget], status: "idle" };
            }
            reroute = true;
            break;
        }
        if (e.created_at) {
          lastEventTime = Math.max(lastEventTime, new Date(e.created_at).getTime());
        }
      }

      return { rebuilt, reroute, lastEventTime, hasLifecycleEvents };
    };

    const maybeRecover = async () => {
      try {
        const [eventsRes, statesRes] = await Promise.all([
          fetch(`${baseUrl}/workflows/${workflowId}/events?limit=200&execution_attempt=${executionAttempt}`, {
            headers: { Authorization: `Bearer ${token}` },
          }),
          fetch(`${baseUrl}/workflows/${workflowId}/states?execution_attempt=${executionAttempt}`, {
            headers: { Authorization: `Bearer ${token}` },
          }),
        ]);

        const eventsBody = await eventsRes.json().catch(() => ({}));
        const statesBody = await statesRes.json().catch(() => []);
        const eventList: WorkflowEvent[] = Array.isArray(eventsBody) ? eventsBody : (eventsBody?.items ?? []);
        rebuildFromEvents(eventList);
        if (SHOW_DEBUG_EVENTS) {
          setDebugEvents(eventList);
        }
        const eventState = rebuildNodeStatesFromEvents(eventList);

        setNodeStates(eventState.rebuilt);
        setHasReroute(eventState.reroute);

        const latestNodeStateTime = (Array.isArray(statesBody) ? statesBody : []).reduce((max, item) => {
          if (!item?.created_at) return max;
          return Math.max(max, new Date(item.created_at).getTime());
        }, 0);
        const latestActivity = Math.max(eventState.lastEventTime, latestNodeStateTime, new Date(workflow.updated_at).getTime());
        const ageMs = Date.now() - latestActivity;
        const allIdle = Object.values(eventState.rebuilt).every((s) => s.status === "idle");
        const shouldRecover =
          workflow.status === "running" &&
          !isPaused &&
          allIdle &&
          !recoveryTriggeredRef.current &&
          (
            (eventState.hasLifecycleEvents && ageMs > 60_000) ||
            (!eventState.hasLifecycleEvents && ageMs > 15_000)
          );

        if (!shouldRecover) return;

        recoveryTriggeredRef.current = true;
        setRecoveryState("recovering");
        const res = await fetch(`${baseUrl}/workflows/${workflowId}/recover`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        qc.invalidateQueries({ queryKey: ["workflow", workflowId] });
      } catch {
        setRecoveryState("failed");
      }
    };

    void maybeRecover();
  }, [workflowId, token, isPaused, workflow.status, workflow.updated_at, executionAttempt, qc, rebuildFromEvents]);

  useWorkflowStream({
    workflowId,
    token,
    enabled: workflow.status === "running" || workflow.status === "paused",
    onEvent: handleEvent,
  });

  return (
    <div className="flex h-full" style={{ backgroundColor: "var(--bg-primary)" }}>
      {/* Left: DAG Canvas + Dialog Input */}
      <div className="flex-1 flex flex-col p-4 gap-3 min-w-0">
        <div className="flex items-center gap-2 shrink-0">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-400" />
          </span>
          <span className="text-sm font-medium text-[var(--text-primary)]">DAG Runtime Canvas</span>
        </div>
        <div className="flex-1 min-h-0">
          <DagCanvas nodeStates={nodeStates} hasReroute={hasReroute} rerouteTarget={rerouteTarget} />
        </div>
        {/* Stale workflow warning */}
        {recoveryState === "recovering" && (
          <div className="shrink-0 rounded-xl border border-amber-500/20 bg-amber-500/10 p-3 flex items-center gap-3">
            <Spinner size={14} />
            <span className="text-xs text-amber-300 flex-1">
              检测到工作流中断，正在从断点自动恢复...
            </span>
          </div>
        )}
        {recoveryState === "failed" && (
          <div className="shrink-0 rounded-xl border border-rose-500/20 bg-rose-500/10 p-3 flex items-center gap-3">
            <span className="text-xs text-rose-300 flex-1">
              自动恢复失败，请返回仪表板重新启动或手动重试。
            </span>
            <Button variant="ghost" size="sm" onClick={() => setRecoveryState("idle")} className="text-xs">
              忽略
            </Button>
          </div>
        )}
        {/* Paused decision card */}
        {isPaused && workflow.pause_state && (
          <div className="shrink-0 rounded-xl border border-amber-500/20 bg-amber-500/5 p-4 space-y-3">
            <div className="flex items-center gap-2">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-400" />
              </span>
              <span className="text-sm font-medium text-amber-300">工作流已暂停</span>
            </div>
            <p className="text-xs text-[var(--text-secondary)]">
              {workflow.pause_state.pause_reason || "等待人工决策"}
            </p>
            {decideError && (
              <p className="text-xs text-rose-400">{decideError}</p>
            )}
            <div className="flex flex-wrap gap-2">
              {(workflow.pause_state.pause_options || []).map((opt) => (
                <Button
                  key={opt.value}
                  variant={opt.value === "approve" ? "outline" : opt.value === "abort" ? "ghost" : "primary"}
                  size="sm"
                  disabled={deciding}
                  onClick={() => handleDecide(opt.value, (opt as { target_node?: string }).target_node)}
                  className="text-xs"
                >
                  {deciding ? "提交中..." : opt.label}
                </Button>
              ))}
            </div>
          </div>
        )}
        {/* Dialog input bar */}
        <div className="shrink-0 flex gap-2">
          <textarea
            value={dialogInput}
            onChange={(e) => {
              setDialogInput(e.target.value);
              e.target.style.height = "auto";
              e.target.style.height = Math.min(e.target.scrollHeight, 96) + "px";
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSendDialog();
              }
            }}
            placeholder="输入反馈或指令，Enter 发送，Shift+Enter 换行..."
            rows={1}
            className="flex-1 resize-none rounded-xl border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2 text-xs text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50 focus-visible:border-emerald-500/50 transition-all"
          />
          <Button onClick={handleSendDialog} variant="primary" size="icon" className="rounded-xl shrink-0">
            <Send size={14} />
          </Button>
        </div>
        {/* Dialog message history */}
        {dialogMessages.length > 0 && (
          <div className="shrink-0 max-h-24 overflow-y-auto space-y-1 px-1">
            {dialogMessages.map((m, i) => (
              <div key={i} className="text-xs flex gap-2">
                <span className="text-[var(--text-muted)] shrink-0">{m.time}</span>
                <span className="text-[var(--text-secondary)]">{m.content}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Right: Node process panel */}
      <div className="w-[720px] border-l border-[var(--border)] flex flex-col min-h-0" style={{ backgroundColor: "var(--bg-primary)" }}>
        <div className={`${SHOW_DEBUG_EVENTS ? "flex-[0_0_58%]" : "flex-1"} min-h-0 flex flex-col`}>
          <div className="px-3 py-2 border-b border-[var(--border)] bg-[var(--bg-elevated)]">
            <span className="text-xs font-medium text-[var(--text-primary)]">节点过程叙述</span>
          </div>
          <StreamPanel
            activeNode={activeNode}
            selectedNode={selectedNode}
            entries={entries}
            onSelectNode={setSelectedNode}
          />
        </div>
        {SHOW_DEBUG_EVENTS && (
          <div className="flex-[0_0_42%] min-h-0 border-t border-[var(--border)] p-3">
            <EventConsole events={debugEvents} />
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── Terminal Tabs ─── */
type TerminalTab = "interview" | "dag" | "report";

function TerminalTabs({ workflowId, token, workflow }: { workflowId: string; token: string; workflow: WorkflowDetail }) {
  const [tab, setTab] = useState<TerminalTab>("report");

  const tabs: { key: TerminalTab; label: string; icon: React.ReactNode }[] = [
    { key: "interview", label: "需求访谈", icon: <MessageSquare size={14} /> },
    { key: "dag", label: "DAG Runtime Canvas", icon: <Network size={14} /> },
    { key: "report", label: "分析报告", icon: <FileText size={14} /> },
  ];

  return (
    <div className="flex flex-col h-[calc(100vh-57px)]">
      <div className="flex items-center gap-1 px-6 py-2 border-b border-[var(--border)] bg-[var(--bg-elevated)]">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg transition-all ${
              tab === t.key
                ? "bg-[var(--bg-card)] text-[var(--text-primary)] font-medium shadow-sm"
                : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
            }`}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>
      <div className="flex-1 min-h-0 relative">
        {tab === "report" && <ReportView workflowId={workflowId} workflowStatus={workflow.status!} executionAttempt={workflow.execution_attempt} />}
        {tab === "dag" && <DagRuntimeView workflowId={workflowId} token={token} workflow={workflow} />}
        {tab === "interview" && <InterviewView workflowId={workflowId} token={token} workflow={workflow} />}
      </div>
    </div>
  );
}

/* ─── Report View ─── */
function ReportView({ workflowId, workflowStatus, executionAttempt }: { workflowId: string; workflowStatus: string; executionAttempt: number }) {
  const { token } = useAuth();
  const { data: artifactList } = useArtifacts(workflowId, true, executionAttempt);
  const [fullArtifacts, setFullArtifacts] = useState<Record<string, unknown>>({});
  const [activeCitation, setActiveCitation] = useState<number | null>(null);
  const [activeSection, setActiveSection] = useState<string | null>(null);
  const [showDownloadConfirm, setShowDownloadConfirm] = useState(false);
  const [showPdfConfirm, setShowPdfConfirm] = useState(false);
  const structuredRef = useRef<HTMLDivElement>(null);

  const reportArtifact = artifactList?.find((a) => a.artifact_type === "report");
  const reportId = reportArtifact?.id;

  // Load report content
  useEffect(() => {
    if (!reportId || !token) return;
    const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
    fetch(`${baseUrl}/artifacts/${reportId}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.json())
      .then((d) => {
        setFullArtifacts((prev) => ({ ...prev, report: d.content }));
      })
      .catch(console.error);
  }, [reportId, token]);

  // Load structured analysis artifacts
  useEffect(() => {
    if (!artifactList || !token) return;
    const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
    const analysisTypes = [
      "feature_matrix",
      "pricing_comparison",
      "user_sentiment",
      "positioning_analysis",
      "swot_analysis",
      "competitor_role_analysis",
      "gtm_analysis",
    ];
    analysisTypes.forEach((type) => {
      const art = artifactList.find((a) => a.artifact_type === type);
      if (!art) return;
      fetch(`${baseUrl}/artifacts/${art.id}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
        .then((r) => r.json())
        .then((d) => {
          setFullArtifacts((prev) => ({ ...prev, [type]: d.content }));
        })
        .catch(console.error);
    });
  }, [artifactList, token]);

  const { data: traceLinks } = useTraceLinks(workflowId, workflowStatus === "completed", executionAttempt);

  const report = fullArtifacts.report as ReportOutput | undefined;
  const swot = fullArtifacts.swot_analysis as SWOTAnalysis | undefined;
  const featureMatrix = fullArtifacts.feature_matrix as FeatureMatrix | undefined;
  const pricingComparison = fullArtifacts.pricing_comparison as PricingComparison | undefined;
  const userSentiment = fullArtifacts.user_sentiment as UserSentimentAnalysis | undefined;
  const competitorRoleAnalysis = fullArtifacts.competitor_role_analysis as CompetitorRoleAnalysis | undefined;

  const [revisions, setRevisions] = useState<Array<{ number: number; passed: boolean; targetNode?: string; score?: number }>>([]);

  useEffect(() => {
    if (workflowStatus !== "completed" && workflowStatus !== "failed") return;
    if (!token) return;
    const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
    fetch(`${baseUrl}/workflows/${workflowId}/events?execution_attempt=${executionAttempt}&limit=200`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.json())
      .then((body: { items?: Array<{ event_type: string; payload: { score?: number; target_node?: string; feedback?: string }; iteration: number }> } | Array<{ event_type: string; payload: { score?: number; target_node?: string; feedback?: string }; iteration: number }>) => {
        const events = Array.isArray(body) ? body : (body?.items ?? []);
        const revs: Array<{ number: number; passed: boolean; targetNode?: string; score?: number }> = [];
        for (const e of events) {
          if (e.event_type === "review_pass") {
            revs.push({ number: e.iteration + 1, passed: true, score: e.payload.score });
          } else if (e.event_type === "review_fail") {
            revs.push({ number: e.iteration + 1, passed: false, targetNode: e.payload.target_node, score: e.payload.score });
          }
        }
        if (revs.length === 0 && workflowStatus === "completed") {
          revs.push({ number: 1, passed: true });
        }
        setRevisions(revs);
      })
      .catch(() => {
        if (workflowStatus === "completed") setRevisions([{ number: 1, passed: true }]);
      });
  }, [workflowId, workflowStatus, token, executionAttempt]);

  return (
    <div className="h-full flex flex-col">
      {revisions.length > 0 && (
        <div className="px-6 py-2 border-b border-zinc-800/80">
          <RevisionTimeline revisions={revisions} />
        </div>
      )}

      <Tabs defaultValue="structured" className="flex-1 flex flex-col px-6 pt-4">
        <div className="flex justify-center mb-4">
          <TabsList>
            <TabsTrigger value="structured" className="gap-2">
              <Layers size={14} /> 结构化看板
            </TabsTrigger>
            <TabsTrigger value="markdown" className="gap-2">
              <FileText size={14} /> Markdown 报告
            </TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="structured" className="flex-1 overflow-y-auto pb-8">
          <div className="flex items-center justify-end">
            {report?.full_markdown && (
              <button
                onClick={() => setShowPdfConfirm(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-xl border border-[var(--border)] bg-[var(--bg-card)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-emerald-500/30 shadow-sm transition-all"
              >
                <Printer size={12} /> 下载 PDF
              </button>
            )}
          </div>
          <div ref={structuredRef} className="space-y-6">
          {competitorRoleAnalysis && <div className="print-section"><CompetitorRoleCard data={competitorRoleAnalysis} /></div>}
          {swot && <div className="print-section"><SwotGrid swot={swot} /></div>}
          {featureMatrix && <div className="print-section"><FeatureMatrixTable data={featureMatrix} /></div>}
          {pricingComparison && <div className="print-section"><PricingTable data={pricingComparison} /></div>}
          {userSentiment && <div className="print-section"><SentimentPanel data={userSentiment} /></div>}
          {!competitorRoleAnalysis && !swot && !featureMatrix && !pricingComparison && !userSentiment && (
            <div className="text-center text-[var(--text-muted)] py-12">加载分析数据中...</div>
          )}
          </div>
        </TabsContent>

        <TabsContent value="markdown" className="flex-1 overflow-hidden">
          <div className="flex h-full gap-4">
            <aside className="w-52 shrink-0">
              {report?.sections && (
                <OutlineNav
                  sections={report.sections}
                  activeSection={activeSection}
                  onSelect={setActiveSection}
                />
              )}
            </aside>
            <main className="flex-1 overflow-y-auto pb-8">
              <div className="flex items-center justify-between mb-4">
                <div />
                {report?.full_markdown && (
                  <button
                    onClick={() => setShowDownloadConfirm(true)}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-xl border border-[var(--border)] bg-[var(--bg-card)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-emerald-500/30 shadow-sm transition-all"
                  >
                    <Download size={12} /> 下载 Markdown
                  </button>
                )}
              </div>
              {report ? (
                <ReportViewer
                  report={report}
                  activeSection={activeSection}
                  onCitationClick={setActiveCitation}
                />
              ) : (
                <div className="text-center text-[var(--text-muted)] py-12">加载报告中...</div>
              )}
            </main>
            {showDownloadConfirm && (
              <div className="fixed inset-0 z-50 flex items-center justify-center">
                <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-6 shadow-xl max-w-sm w-full space-y-4">
                  <p className="text-sm font-medium text-[var(--text-primary)]">确认下载报告？</p>
                  <p className="text-xs text-[var(--text-muted)]">文件名：{report?.title || "竞品分析报告"}.md</p>
                  <div className="flex gap-2 justify-end">
                    <button
                      onClick={() => setShowDownloadConfirm(false)}
                      className="px-4 py-1.5 text-xs rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
                    >
                      取消
                    </button>
                    <button
                      onClick={() => {
                        if (!report?.full_markdown) return;
                        const blob = new Blob([report.full_markdown], { type: "text/markdown;charset=utf-8" });
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement("a");
                        a.href = url;
                        a.download = `${report.title || "竞品分析报告"}.md`;
                        a.click();
                        URL.revokeObjectURL(url);
                        setShowDownloadConfirm(false);
                      }}
                      className="px-4 py-1.5 text-xs rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white transition-colors"
                    >
                      确认下载
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </TabsContent>
      </Tabs>
      {showPdfConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-6 shadow-xl max-w-sm w-full space-y-4">
            <p className="text-sm font-medium text-[var(--text-primary)]">确认为 PDF 打印？</p>
            <p className="text-xs text-[var(--text-muted)]">
              将在新窗口中打开报告内容并自动弹出打印对话框，选择「另存为 PDF」即可保存。
            </p>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setShowPdfConfirm(false)}
                className="px-4 py-1.5 text-xs rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
              >
                取消
              </button>
              <button
                onClick={() => {
                  setShowPdfConfirm(false);
                  const el = structuredRef.current;
                  if (!el) return;
                  const printWindow = window.open("", "_blank");
                  if (!printWindow) return;
                  const styles = Array.from(document.querySelectorAll("style, link[rel=stylesheet]"))
                    .map((s) => s.outerHTML).join("\n");
                  const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${report?.title || "竞品分析报告"}</title>${styles}<style>@page{margin:48px 24px 24px}body{font-family:"PingFang SC","Microsoft YaHei",sans-serif;max-width:900px;margin:0 auto;padding:40px 20px 20px;color:#1a1a1a;-webkit-print-color-adjust:exact;print-color-adjust:exact}.print-title{text-align:center;font-size:22px;font-weight:700;margin-bottom:32px;padding-bottom:16px;border-bottom:2px solid #e5e7eb}.print-section{page-break-after:always;padding-top:24px}.print-section:last-child{page-break-after:auto}@media print{body{margin:0;padding:0}}</style></head><body><h1 class="print-title">结构化看板</h1>${el.innerHTML}</body></html>`;
                  printWindow.document.write(html);
                  printWindow.document.close();
                  printWindow.onload = () => { setTimeout(() => printWindow.print(), 300); };
                }}
                className="px-4 py-1.5 text-xs rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white transition-colors"
              >
                确认打印
              </button>
            </div>
          </div>
        </div>
      )}
      <EvidencePanel
        citations={report?.citations ?? []}
        traceLinks={traceLinks ?? []}
        activeCitationIndex={activeCitation}
        onClose={() => setActiveCitation(null)}
      />
    </div>
  );
}
