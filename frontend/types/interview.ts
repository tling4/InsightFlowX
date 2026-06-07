import type { CompetitorGroups, WorkflowConfig } from "./workflow";

export type InterviewMessageRole = "user" | "assistant";

export interface InterviewMessage {
  id?: string;
  role: InterviewMessageRole;
  content: string;
  created_at: string;
}

export interface InterviewInput {
  user_message: string;
}

export interface InterviewSSEMessage {
  token?: string;
  extracted_config?: Partial<WorkflowConfig>;
  suggested_competitors?: string[];
  suggested_competitor_groups?: CompetitorGroups;
  is_complete?: boolean;
  response?: string;
}
