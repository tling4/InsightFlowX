"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useWorkflow, useStartWorkflow } from "@/lib/use-workflow";
import { useInterviewHistory } from "@/lib/use-interview";
import { useArtifacts } from "@/lib/use-artifacts";
import { useTraceLinks } from "@/lib/use-trace";
import { useInterviewStream } from "@/lib/use-interview-stream";
import { useWorkflowStream } from "@/lib/use-workflow-stream";
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
import { EventConsole } from "@/components/events/event-console";
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
import type { WorkflowConfig } from "@/types/workflow";
import type { WorkflowEvent, AgentNodeName } from "@/types/event";
import type { ReportOutput, SWOTAnalysis, FeatureMatrix, ArtifactListItem } from "@/types/artifact";
import type { TraceLink } from "@/types/trace";

export default function WorkflowStudioPage() {
  const { id } = useParams<{ id: string }>();
  const { token } = useAuth();
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

  return (
    <AuthGuard>
      <div className="min-h-screen" style={{ backgroundColor: "var(--bg-primary)" }}>
        <Header workflow={workflow} />
        {status === "configuring" && <InterviewView workflowId={id} token={token!} />}
        {status === "running" && <DagRuntimeView workflowId={id} token={token!} />}
        {(status === "completed" || status === "failed") && (
          <ReportView workflowId={id} workflowStatus={status!} />
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
function InterviewView({ workflowId, token }: { workflowId: string; token: string }) {
  const [messages, setMessages] = useState<InterviewMessage[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isComplete, setIsComplete] = useState(false);
  const [config, setConfig] = useState<Partial<WorkflowConfig>>({});
  const [newCompetitor, setNewCompetitor] = useState("");
  const { sendMessage, cancel, isStreaming } = useInterviewStream({ workflowId, token });
  const startMutation = useStartWorkflow();
  const { data: history } = useInterviewHistory(workflowId);

  useEffect(() => {
    if (history && history.length > 0) {
      setMessages(history);
    }
  }, [history]);

  const sendUserMessage = (text: string) => {
    if (!text.trim() || isStreaming || isComplete) return;
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
        if (incoming.suggested_competitors) {
          setConfig((prev) => ({
            ...prev,
            competitors: [...new Set([...(prev.competitors ?? []), ...incoming.suggested_competitors!])],
          }));
        }
        if (incoming.is_complete && incoming.extracted_config) {
          setIsComplete(true);
        }
      },
      // onComplete: only lock when META says complete AND config was extracted
      () => {},
      (err) => console.error("Interview SSE error:", err)
    );
  };

  const handleSend = () => sendUserMessage(inputValue);
  const handleQuickReply = (text: string) => sendUserMessage(text);

  const handleStart = async () => {
    await startMutation.mutateAsync(workflowId);
  };

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
              placeholder={isComplete ? "配置已锁定，请在右侧确认启动..." : "输入回复，或点击上方的选项卡片快速选择... (Enter 发送，Shift+Enter 换行)"}
              disabled={isComplete || isStreaming}
              rows={1}
              className="flex-1 resize-none rounded-2xl border border-[var(--border)] bg-[var(--bg-elevated)] px-4 py-2.5 text-sm text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/50 focus-visible:border-emerald-500/50 disabled:opacity-50 transition-all"
            />
            <Button onClick={handleSend} disabled={isComplete || isStreaming} variant="primary" size="icon" className="rounded-xl">
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
          onNewCompetitorChange={setNewCompetitor}
          onAddCompetitor={() => {
            if (newCompetitor.trim()) {
              setConfig((prev) => ({
                ...prev,
                competitors: [...(prev.competitors ?? []), newCompetitor.trim()],
              }));
              setNewCompetitor("");
            }
          }}
          onRemoveCompetitor={(name) =>
            setConfig((prev) => ({
              ...prev,
              competitors: (prev.competitors ?? []).filter((c) => c !== name),
            }))
          }
          onConfigChange={(field, value) => setConfig((prev) => ({ ...prev, [field]: value }))}
          onStart={handleStart}
        />
      </div>
    </div>
  );
}

/* ─── DAG Runtime View ─── */
function DagRuntimeView({ workflowId, token }: { workflowId: string; token: string }) {
  const [events, setEvents] = useState<WorkflowEvent[]>([]);
  const [nodeStates, setNodeStates] = useState<
    Record<AgentNodeName, { status: NodeStatus; message?: string; duration_ms?: number }>
  >({
    information_collection: { status: "idle" },
    analysis: { status: "idle" },
    report_writing: { status: "idle" },
    review: { status: "idle" },
  });
  const [hasReroute, setHasReroute] = useState(false);

  const handleEvent = useCallback((e: WorkflowEvent) => {
    setEvents((prev) => [...prev, e]);
    setNodeStates((prev) => {
      const next = { ...prev };
      const node = e.node_name as AgentNodeName;
      if (!node) return next;

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
          next.review = { ...next.review, status: "rerouted", message: "Rerouting..." };
          if (payload?.target_node) {
            next[payload.target_node as AgentNodeName] = { ...next[payload.target_node as AgentNodeName], status: "idle" };
          }
          setHasReroute(true);
          break;
      }
      return next;
    });
  }, []);

  // Replay historical events on mount (for page revisit)
  useEffect(() => {
    const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
    fetch(`${baseUrl}/workflows/${workflowId}/events`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.json())
      .then((history: WorkflowEvent[]) => {
        if (!Array.isArray(history)) return;
        // Sort by seq to replay in order
        const sorted = [...history].sort((a, b) => a.seq - b.seq);
        setEvents(sorted);
        // Rebuild node states from history
        setNodeStates(() => {
          const rebuilt: Record<AgentNodeName, { status: NodeStatus; message?: string; duration_ms?: number }> = {
            information_collection: { status: "idle" },
            analysis: { status: "idle" },
            report_writing: { status: "idle" },
            review: { status: "idle" },
          };
          let reroute = false;
          for (const e of sorted) {
            const node = e.node_name as AgentNodeName;
            if (!node) continue;
            const payload = e.payload as Record<string, unknown> | undefined;
            switch (e.event_type) {
              case "node_start":
                rebuilt[node] = { ...rebuilt[node], status: "active", message: "Running..." };
                break;
              case "node_complete":
                rebuilt[node] = { ...rebuilt[node], status: "completed", message: "Completed", duration_ms: payload?.duration_ms as number };
                break;
              case "node_error":
                rebuilt[node] = { ...rebuilt[node], status: "failed", message: (payload?.error_message as string) || "Error" };
                break;
              case "review_reroute":
                rebuilt.review = { ...rebuilt.review, status: "rerouted", message: "Rerouting..." };
                if (payload?.target_node) {
                  rebuilt[payload.target_node as AgentNodeName] = { ...rebuilt[payload.target_node as AgentNodeName], status: "idle" };
                }
                reroute = true;
                break;
            }
          }
          setHasReroute(reroute);
          return rebuilt;
        });
      })
      .catch(() => {});
  }, [workflowId, token]);

  useWorkflowStream({
    workflowId,
    token,
    enabled: true,
    onEvent: handleEvent,
  });

  return (
    <div className="flex h-[calc(100vh-57px)]" style={{ backgroundColor: "var(--bg-primary)" }}>
      <div className="flex-1 flex flex-col p-4 gap-3">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-400" />
          </span>
          <span className="text-sm font-medium text-[var(--text-primary)]">DAG Runtime Canvas</span>
        </div>
        <div className="flex-1">
          <DagCanvas nodeStates={nodeStates} hasReroute={hasReroute} />
        </div>
      </div>
      <div className="w-[400px] border-l border-[var(--border)] p-4 flex flex-col gap-3" style={{ backgroundColor: "var(--bg-primary)" }}>
        <EventConsole events={events} />
      </div>
    </div>
  );
}

/* ─── Report View ─── */
function ReportView({ workflowId, workflowStatus }: { workflowId: string; workflowStatus: string }) {
  const { data: artifactList } = useArtifacts(workflowId);
  const [fullArtifacts, setFullArtifacts] = useState<Record<string, unknown>>({});
  const [activeCitation, setActiveCitation] = useState<number | null>(null);
  const [activeSection, setActiveSection] = useState<string | null>(null);

  const reportArtifact = artifactList?.find((a) => a.artifact_type === "report");
  const reportId = reportArtifact?.id;

  // Load report content
  useEffect(() => {
    if (!reportId) return;
    const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
    const token = localStorage.getItem("access_token");
    fetch(`${baseUrl}/artifacts/${reportId}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.json())
      .then((d) => {
        setFullArtifacts((prev) => ({ ...prev, report: d.content }));
      })
      .catch(console.error);
  }, [reportId]);

  // Load structured analysis artifacts
  useEffect(() => {
    if (!artifactList) return;
    const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
    const token = localStorage.getItem("access_token");
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
  }, [artifactList]);

  const { data: traceLinks } = useTraceLinks(workflowId, workflowStatus === "completed");

  const report = fullArtifacts.report as ReportOutput | undefined;
  const swot = fullArtifacts.swot_analysis as SWOTAnalysis | undefined;
  const featureMatrix = fullArtifacts.feature_matrix as FeatureMatrix | undefined;

  const [revisions, setRevisions] = useState<Array<{ number: number; passed: boolean; targetNode?: string; score?: number }>>([]);

  useEffect(() => {
    if (workflowStatus !== "completed" && workflowStatus !== "failed") return;
    const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
    const token = localStorage.getItem("access_token");
    fetch(`${baseUrl}/workflows/${workflowId}/events?event_type=review_pass&event_type=review_fail&event_type=review_reroute`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.json())
      .then((events: Array<{ event_type: string; payload: { score?: number; target_node?: string; feedback?: string }; iteration: number }>) => {
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
  }, [workflowId, workflowStatus]);

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
