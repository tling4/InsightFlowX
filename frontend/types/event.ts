export type EventType =
  | "node_start"
  | "node_complete"
  | "node_error"
  | "review_pass"
  | "review_fail"
  | "review_reroute"
  | "tool_call"
  | "tool_result"
  | "llm_request"
  | "llm_response"
  | "workflow_start"
  | "workflow_complete"
  | "workflow_failed"
  | "workflow_paused"
  | "context_compressed";

export type AgentNodeName =
  | "information_collection"
  | "analysis"
  | "report_writing"
  | "review";

export interface WorkflowEvent {
  id: string;
  workflow_id: string;
  node_name: AgentNodeName;
  iteration: number;
  event_type: EventType;
  seq: number;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface NodeState {
  node: AgentNodeName;
  status: "idle" | "active" | "completed" | "failed" | "rerouted";
  message?: string;
  duration_ms?: number;
  started_at?: string;
}
