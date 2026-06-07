export type WorkflowStatus =
  | "created"
  | "configuring"
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

export type ProductCategory =
  | "企业软件 / SaaS"
  | "AI 产品 / 智能助手"
  | "移动应用"
  | "硬件 / 消费电子"
  | "平台 / 社区 / 内容"
  | "电商 / 零售 / 本地生活"
  | "SaaS / 协作工具"
  | "硬件产品";

export interface ProductProfile {
  canonical_name: string;
  product_form: string;
  market_category: string;
  brand: string;
  product_line: string;
  model: string;
  variant_tier: string;
  market_segment: string;
  competition_basis: string[];
  exclude_relations: string[];
}

export interface CompetitorGroups {
  core: string[];
  benchmark: string[];
  potential: string[];
  substitute: string[];
  pitfall: string[];
}

export interface WorkflowConfig {
  target_product: string;
  product_category: ProductCategory;
  product_profile?: ProductProfile | null;
  focus_dimensions: string[];
  competitor_count: number;
  competitor_groups: CompetitorGroups;
  competitors: string[];
  language: string;
  extra_requirements: string;
}

export interface WorkflowDetail {
  id: string;
  title: string;
  status: WorkflowStatus;
  current_phase: string;
  config: Partial<WorkflowConfig>;
  revision_count: number;
  execution_attempt: number;
  max_revisions?: number;
  total_tokens?: number;
  error_message?: string | null;
  pause_state?: {
    paused_by_node: string;
    pause_reason: string;
    pause_options: Array<{ value: string; label: string; target_node?: string; requires_input?: boolean }>;
    pause_context?: {
      score?: number;
      checks?: Array<{ dimension: string; passed: boolean; detail: string }>;
      specific_issues?: string[];
      target_node?: string;
      primary_issue_type?: string | null;
      issue_types?: string[];
      affected_entities?: string[];
      affected_artifacts?: string[];
      suggested_actions?: string[];
      retry_worthiness?: "high" | "medium" | "low" | "none" | "unknown" | string;
      retry_scope?: string | null;
      [key: string]: unknown;
    };
    /** 暂停时 DAG state 快照（供 resume 复用 cached_review_result） */
    dag_state?: Record<string, unknown>;
    paused_at: string;
  } | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}
