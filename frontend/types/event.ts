export type EventType =
  | "node_start"
  | "node_progress"
  | "node_complete"
  | "node_error"
  | "review_pass"
  | "review_fail"
  | "review_failed_max_revisions"
  | "reroute"
  | "tool_call"
  | "tool_result"
  | "llm_request"
  | "llm_response"
  | "llm_stream"
  | "workflow_start"
  | "workflow_complete"
  | "workflow_failed"
  | "workflow_paused"
  | "workflow_resumed"
  | "context_compressed";

export type AgentNodeName =
  | "information_collection"
  | "analysis"
  | "feature_analysis"
  | "pricing_analysis"
  | "sentiment_analysis"
  | "positioning_analysis"
  | "role_analysis"
  | "gtm_analysis"
  | "report_writing"
  | "review";

export const AGENT_NODE_ORDER: AgentNodeName[] = [
  "information_collection",
  "analysis",
  "feature_analysis",
  "pricing_analysis",
  "sentiment_analysis",
  "positioning_analysis",
  "role_analysis",
  "gtm_analysis",
  "report_writing",
  "review",
];

export interface WorkflowEvent {
  id?: string;
  workflow_id?: string;
  node_name?: AgentNodeName;
  iteration?: number;
  event_type: EventType;
  seq?: number;
  payload: Record<string, unknown>;
  created_at: string;
  content?: string;
}

export interface NodeState {
  node: AgentNodeName;
  status: "idle" | "active" | "completed" | "failed" | "rerouted";
  message?: string;
  duration_ms?: number;
  started_at?: string;
}

export type NodeProgressLevel = "info" | "success" | "warning" | "error";

export interface NodeProgressEntry {
  node: AgentNodeName;
  stage: string;
  message: string;
  level: NodeProgressLevel;
  created_at: string;
  seq?: number;
  event_type: EventType;
}
