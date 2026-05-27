export interface ApiResponse<T> {
  data: T;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface UserRegister {
  username: string;
  email: string;
  password: string;
}

export interface UserLogin {
  email: string;
  password: string;
}

export interface UserResponse {
  id: string;
  username: string;
  email: string;
  display_name: string | null;
  is_active: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
}

export interface WorkflowCreate {
  title: string;
}

import type { WorkflowStatus } from "./workflow";

export interface WorkflowListItem {
  id: string;
  title: string;
  status: WorkflowStatus;
  current_phase: string;
  revision_count: number;
  created_at: string;
  updated_at: string;
}
