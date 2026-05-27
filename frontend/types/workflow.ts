export type WorkflowStatus =
  | "created"
  | "configuring"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type ProductCategory = "SaaS / 协作工具" | "移动应用" | "硬件产品";

export interface WorkflowConfig {
  target_product: string;
  product_category: ProductCategory;
  focus_dimensions: string[];
  competitor_count: number;
  competitors: string[];
  language: string;
  extra_requirements: string;
}

export interface PhaseStatus {
  status: "pending" | "running" | "completed" | "failed";
  started_at?: string;
  duration_ms?: number;
}

export interface WorkflowDetail {
  id: string;
  title: string;
  status: WorkflowStatus;
  current_phase: string;
  config: WorkflowConfig;
  revision_count: number;
  progress: {
    phases: {
      collecting: PhaseStatus;
      analyzing: PhaseStatus;
      writing: PhaseStatus;
      reviewing: PhaseStatus;
    };
    total_tokens: number;
  };
  created_at: string;
  updated_at: string;
}
