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
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { ChatStream } from "@/components/interview/chat-stream";
import { ConfigPanel } from "@/components/interview/config-panel";
import { DagCanvas } from "@/components/dag/dag-canvas";
import type { NodeStatus } from "@/components/dag/dag-canvas";
import { StreamPanel } from "@/components/events/stream-panel";
import { ReportViewer } from "@/components/report/report-viewer";
import { OutlineNav } from "@/components/report/outline-nav";
import { EvidencePanel } from "@/components/report/evidence-panel";
import { SwotGrid } from "@/components/report/swot-grid";
import { FeatureMatrixTable } from "@/components/report/feature-matrix-table";
import { RevisionTimeline } from "@/components/report/revision-timeline";
import { Send, ArrowLeft, Layers, FileText } from "lucide-react";
import Link from "next/link";
import { statusLabel, statusColor } from "@/lib/utils";
import type { InterviewMessage } from "@/types/interview";
import type { WorkflowConfig, WorkflowDetail } from "@/types/workflow";
import type { WorkflowEvent, AgentNodeName } from "@/types/event";
import type { ReportOutput, SWOTAnalysis, FeatureMatrix, ArtifactListItem } from "@/types/artifact";
import type { TraceLink } from "@/types/trace";

export default function WorkflowStudioPage() {
  const { id } = useParams<{ id: string }>();
  const { token } = useAuth();
  const qc = useQueryClient();
  const { data: workflow, isLoading } = useWorkflow(id);
  const status = workflow?.status;

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
        <Header workflow={workflow} />
        {isInterviewStage && <InterviewView workflowId={id} token={token!} workflow={workflow} />}
        {isRuntimeStage && <DagRuntimeView workflowId={id} token={token!} workflow={workflow} />}
        {isTerminalStage && <ReportView workflowId={id} workflowStatus={status!} executionAttempt={workflow.execution_attempt} />}
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

function Header({ workflow }: { workflow: { title?: string; status?: string; current_phase?: string; revision_count?: number } | undefined }) {
  return (
    <header className="border-b border-[var(--border)] bg-[var(--bg-primary)]/80 backdrop-blur-xl sticky top-0 z-10">
      <div className="flex items-center justify-between px-6 py-3">
        <div className="flex items-center gap-3">
          <Link href="/dashboard" className="text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors">
            <ArrowLeft size={18} />
          </Link>
          <h1 className="text-lg font-bold text-[var(--text-primary)]">{workflow?.title || "Workflow"}</h1>
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
function InterviewView({ workflowId, token, workflow }: { workflowId: string; token: string; workflow: WorkflowDetail }) {
  // 重进入水合：useState 懒初始化从 workflow.config 一次性恢复右侧面板和 isComplete，
  // 之后用户编辑或 SSE 增量不会被后续 useWorkflow 重取数据覆盖
  const [config, setConfig] = useState<Partial<WorkflowConfig>>(() => {
    const sc = workflow.config as Partial<WorkflowConfig> | undefined;
    return sc && Object.keys(sc).length > 0 ? { ...sc } : {};
  });
  const [isComplete, setIsComplete] = useState<boolean>(() => {
    const sc = workflow.config as Partial<WorkflowConfig> | undefined;
    // target_product + product_category 都已存在视为"可直接启动"
    return Boolean(sc?.target_product && sc?.product_category);
  });
  const [messages, setMessages] = useState<InterviewMessage[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [newCompetitor, setNewCompetitor] = useState("");
  const [startError, setStartError] = useState<string | null>(null);
  const { sendMessage, isStreaming } = useInterviewStream({ workflowId, token });
  const startMutation = useStartWorkflow();
  const { data: history } = useInterviewHistory(workflowId);

  useEffect(() => {
    if (history && history.length > 0) {
      setMessages(history);
    }
  }, [history]);

  // 本地校验：target_product + product_category 必须都存在
  const canStart = Boolean(config.target_product && config.product_category);

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
          setConfig((prev) => ({ ...prev, ...incoming.extracted_config }));
        }
        const competitors = incoming.suggested_competitors;
        if (competitors && competitors.length > 0) {
          setConfig((prev) => ({
            ...prev,
            competitors: [...new Set([...(prev.competitors ?? []), ...competitors])],
          }));
        }
      },
      // onComplete: stream finished with CONFIG_COMPLETE sentinel — lock config
      () => {
        setIsComplete(true);
      },
      (err) => console.error("Interview SSE error:", err)
    );
  };

  const handleSend = () => sendUserMessage(inputValue);
  const handleQuickReply = (text: string) => sendUserMessage(text);
  // 解锁继续编辑：让用户在 isComplete=true 后还能继续访谈来修订
  const handleResumeEditing = () => {
    setIsComplete(false);
    setStartError(null);
  };

  const handleStart = async () => {
    setStartError(null);
    if (!canStart) {
      setStartError("配置不完整：target_product 和 product_category 必填");
      return;
    }
    try {
      // 将右侧面板编辑的 config 作为权威配置传给后端
      await startMutation.mutateAsync({ id: workflowId, config });
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string; message?: string } } })?.response?.data?.detail
        || (err as { response?: { data?: { detail?: string; message?: string } } })?.response?.data?.message
        || (err as Error).message
        || "启动失败";
      setStartError(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
  };

  // 用户编辑右侧面板时清空 startError，避免误导
  const clearStartError = () => { if (startError) setStartError(null); };

  // 安全网：isComplete 翻转但 config 仍空时，从后端拉一次（兼容旧 META 路径）
  useEffect(() => {
    if (!isComplete || canStart) return;
    const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
    fetch(`${baseUrl}/workflows/${workflowId}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.json())
      .then((data) => {
        if (data?.config) {
          setConfig((prev) => ({ ...data.config, ...prev }));
        }
      })
      .catch(() => {});
  }, [isComplete, canStart, workflowId, token]);

  return (
    <div className="flex h-[calc(100vh-57px)]" style={{ backgroundColor: "var(--bg-primary)" }}>
      <div className="flex flex-col w-[65%] border-r border-[var(--border)]" style={{ backgroundColor: "var(--bg-primary)" }}>
        <div className="px-5 py-3 border-b border-[var(--border)]">
          <h2 className="text-sm font-semibold text-[var(--text-primary)]">竞品分析需求访谈</h2>
          <p className="text-xs text-[var(--text-muted)] mt-0.5">AI 将通过对话引导你完成分析配置</p>
        </div>
        <ChatStream messages={messages} isStreaming={isStreaming} onQuickReply={handleQuickReply} />
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
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder={isStreaming ? "AI 正在回复中..." : "输入回复，或继续追问以完善配置... (Enter 发送，Shift+Enter 换行)"}
              disabled={isStreaming}
              rows={1}
              className="flex-1 resize-none rounded-2xl border border-[var(--border)] bg-[var(--bg-elevated)] px-4 py-2.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50 focus-visible:border-emerald-500/50 disabled:opacity-50 transition-all"
            />
            <Button onClick={handleSend} disabled={isStreaming} variant="primary" size="icon" className="rounded-xl">
              <Send size={16} />
            </Button>
          </div>
        </div>
      </div>
      <div className="w-[35%] p-5 backdrop-blur-xl bg-[var(--bg-primary)]/60 border-l border-[var(--border)]">
        <ConfigPanel
          config={config}
          isComplete={isComplete}
          isStarting={startMutation.isPending}
          newCompetitor={newCompetitor}
          canStart={canStart}
          startError={startError}
          onNewCompetitorChange={setNewCompetitor}
          onAddCompetitor={() => {
            if (newCompetitor.trim()) {
              setConfig((prev) => ({
                ...prev,
                competitors: [...(prev.competitors ?? []), newCompetitor.trim()],
              }));
              setNewCompetitor("");
              clearStartError();
            }
          }}
          onRemoveCompetitor={(name) => {
            setConfig((prev) => ({
              ...prev,
              competitors: (prev.competitors ?? []).filter((c) => c !== name),
            }));
            clearStartError();
          }}
          onConfigChange={(field, value) => {
            setConfig((prev) => ({ ...prev, [field]: value }));
            clearStartError();
          }}
          onStart={handleStart}
          onResumeEditing={handleResumeEditing}
        />
      </div>
    </div>
  );
}

/* ─── DAG Runtime View ─── */
function DagRuntimeView({ workflowId, token, workflow }: { workflowId: string; token: string; workflow: WorkflowDetail }) {
  const qc = useQueryClient();
  const isPaused = workflow.status === "paused";
  const executionAttempt = workflow.execution_attempt;
  const [nodeStates, setNodeStates] = useState<
    Record<AgentNodeName, { status: NodeStatus; message?: string; duration_ms?: number }>
  >({
    information_collection: { status: "idle" },
    analysis: { status: "idle" },
    report_writing: { status: "idle" },
    review: { status: "idle" },
  });
  const [hasReroute, setHasReroute] = useState(false);
  const { activeNode, texts, pushToken, setActiveNode } = useNodeStream();
  const [dialogInput, setDialogInput] = useState("");
  const [dialogMessages, setDialogMessages] = useState<Array<{ role: "user" | "system"; content: string; time: string }>>([]);
  const [deciding, setDeciding] = useState(false);
  const [decideError, setDecideError] = useState<string | null>(null);
  const [recoveryState, setRecoveryState] = useState<"idle" | "recovering" | "failed">("idle");
  const recoveryTriggeredRef = useRef(false);

  const handleEvent = useCallback((e: WorkflowEvent) => {
    // llm_stream events carry per-token content at top level (not in payload)
    if (e.event_type === "llm_stream") {
      const content = (e as unknown as { content: string }).content;
      if (content && e.node_name) {
        pushToken(e.node_name as AgentNodeName, content);
      }
      return;
    }

    // Track active node to reset stream panel when a new node starts
    if (e.event_type === "node_start" && e.node_name) {
      setActiveNode(e.node_name as AgentNodeName);
      setRecoveryState("idle");
    }

    // Only node lifecycle events affect nodeStates; skip irrelevant ones
    // to prevent ReactFlow from rebuilding all nodes on every SSE event
    const NODE_EVENTS = ["node_start", "node_complete", "node_error", "review_reroute", "reroute"];
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
        case "review_reroute":
        case "reroute":
          next.review = { ...next.review, status: "rerouted", message: "Rerouting..." };
          if (payload?.target_node) {
            next[payload.target_node as AgentNodeName] = { ...next[payload.target_node as AgentNodeName], status: "idle" };
          }
          break;
      }
      return next;
    });

    if (e.event_type === "review_reroute" || e.event_type === "reroute") {
      setHasReroute(true);
    }
  }, [pushToken, setActiveNode]);

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
      // 失效 workflow 缓存：approve→completed / abort→cancelled / jump→running 切换不依赖 SSE 到达
      qc.invalidateQueries({ queryKey: ["workflow", workflowId] });
      qc.invalidateQueries({ queryKey: ["workflows"] });
    } catch (err) {
      setDecideError((err as Error).message || "决策提交失败");
    } finally {
      setDeciding(false);
    }
  };

  // Replay current-attempt history on mount, then recover if the workflow is stale.
  useEffect(() => {
    recoveryTriggeredRef.current = false;
    queueMicrotask(() => setRecoveryState("idle"));

    const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";

    const rebuildFromEvents = (list: WorkflowEvent[]) => {
      const rebuilt: Record<AgentNodeName, { status: NodeStatus; message?: string; duration_ms?: number }> = {
        information_collection: { status: "idle" },
        analysis: { status: "idle" },
        report_writing: { status: "idle" },
        review: { status: "idle" },
      };
      let reroute = false;
      let lastEventTime = 0;
      let hasLifecycleEvents = false;

      for (const e of [...list].sort((a, b) => a.seq - b.seq)) {
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
          case "review_reroute":
          case "reroute":
            rebuilt.review = { ...rebuilt.review, status: "rerouted", message: "Rerouting..." };
            if (payload?.target_node) {
              rebuilt[payload.target_node as AgentNodeName] = { ...rebuilt[payload.target_node as AgentNodeName], status: "idle" };
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
        const eventState = rebuildFromEvents(eventList);

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
  }, [workflowId, token, isPaused, workflow.status, workflow.updated_at, executionAttempt, qc]);

  useWorkflowStream({
    workflowId,
    token,
    enabled: true,
    onEvent: handleEvent,
  });

  return (
    <div className="flex h-[calc(100vh-57px)]" style={{ backgroundColor: "var(--bg-primary)" }}>
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
          <DagCanvas nodeStates={nodeStates} hasReroute={hasReroute} />
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

      {/* Right: Live Stream panel */}
      <div className="w-[400px] border-l border-[var(--border)] flex flex-col" style={{ backgroundColor: "var(--bg-primary)" }}>
        <div className="px-3 py-2 border-b border-[var(--border)] bg-[var(--bg-elevated)]">
          <span className="text-xs font-medium text-[var(--text-primary)]">Live Stream</span>
        </div>
        <StreamPanel activeNode={activeNode} texts={texts} />
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
    const analysisTypes = ["feature_matrix", "pricing_comparison", "user_sentiment", "swot_analysis"];
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

  const [revisions, setRevisions] = useState<Array<{ number: number; passed: boolean; targetNode?: string; score?: number }>>([]);

  useEffect(() => {
    if (workflowStatus !== "completed" && workflowStatus !== "failed") return;
    if (!token) return;
    const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
    fetch(`${baseUrl}/workflows/${workflowId}/events?event_type=review_pass&event_type=review_fail&event_type=review_reroute&execution_attempt=${executionAttempt}`, {
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
    <div className="h-[calc(100vh-57px)] flex flex-col">
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

        <TabsContent value="structured" className="flex-1 overflow-y-auto space-y-6 pb-8">
          {swot && <SwotGrid swot={swot} />}
          {featureMatrix && <FeatureMatrixTable data={featureMatrix} />}
          {!swot && !featureMatrix && (
            <div className="text-center text-[var(--text-muted)] py-12">加载分析数据中...</div>
          )}
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
          </div>
        </TabsContent>
      </Tabs>
      <EvidencePanel
        citations={report?.citations ?? []}
        traceLinks={traceLinks ?? []}
        activeCitationIndex={activeCitation}
        onClose={() => setActiveCitation(null)}
      />
    </div>
  );
}
