import type { WorkflowConfig } from "./workflow";

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
  is_complete?: boolean;
  response?: string;
}
