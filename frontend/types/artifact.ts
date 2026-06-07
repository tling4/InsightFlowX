export type ArtifactType =
  | "collection_raw"
  | "feature_matrix"
  | "pricing_comparison"
  | "user_sentiment"
  | "positioning_analysis"
  | "swot_analysis"
  | "competitor_role_analysis"
  | "gtm_analysis"
  | "report";

export interface ArtifactListItem {
  id: string;
  artifact_type: ArtifactType;
  title: string;
  created_by_node: string;
  format_version: string;
  created_at: string;
}

export interface ArtifactDetail extends ArtifactListItem {
  content: Record<string, unknown>;
  content_text: string | null;
}

export interface ReportSection {
  heading: string;
  level: number;
  content: string;
  source_refs: string[];
}

export interface Citation {
  index: number;
  url: string;
  title: string;
  access_date: string;
}

export interface ReportOutput {
  title: string;
  executive_summary: string;
  sections: ReportSection[];
  citations: Citation[];
  full_markdown: string;
  generated_at: string;
}

export interface FeatureMatrix {
  dimensions: string[];
  matrix: Array<{
    module?: string;
    feature_name: string;
    comparisons?: Array<{
      product: string;
      support_level: string;
      difference_summary: string;
      evidence_refs?: EvidenceRef[];
    }>;
    products: Record<string, string>;
  }>;
}

export interface PricingComparison {
  plans: Array<{
    product: string;
    tiers: Array<{
      name: string;
      price: number;
      raw_price?: string;
      currency?: string;
      billing_period?: string;
      pricing_model?: string;
      highlights: string[];
      evidence_refs?: EvidenceRef[];
    }>;
  }>;
  summary: string;
}

export interface EvidenceRef {
  url: string;
  title: string;
  snippet: string;
  source_type: string;
  confidence: number;
  captured_at?: string | null;
}

export interface UserSentimentAnalysis {
  per_product: Record<string, { positive: number; negative: number; neutral: number }>;
  common_praises: string[];
  common_complaints: string[];
}

export interface SWOTAnalysis {
  product: string;
  strengths: string[];
  weaknesses: string[];
  opportunities: string[];
  threats: string[];
  source_refs: Record<string, string[]>;
}

export interface CompetitorRoleAnalysis {
  items: Array<{
    product: string;
    role: "core" | "benchmark" | "potential" | "substitute" | "pitfall" | "unknown";
    reason: string;
    evidence_refs?: EvidenceRef[];
    confidence?: number;
  }>;
  summary: string;
}

export interface PositioningAnalysis {
  target_users: { summary: string; evidence_refs?: EvidenceRef[]; confidence?: number };
  scenarios: { summary: string; evidence_refs?: EvidenceRef[]; confidence?: number };
  problems: { summary: string; evidence_refs?: EvidenceRef[]; confidence?: number };
  solutions: { summary: string; evidence_refs?: EvidenceRef[]; confidence?: number };
  rtb: { summary: string; evidence_refs?: EvidenceRef[]; confidence?: number };
  summary: string;
}

export interface GTMAnalysis {
  launch_rhythm: { summary: string; evidence_refs?: EvidenceRef[]; confidence?: number };
  budget_allocation: { summary: string; evidence_refs?: EvidenceRef[]; confidence?: number };
  channel_mix: { summary: string; evidence_refs?: EvidenceRef[]; confidence?: number };
  content_strategy: { summary: string; evidence_refs?: EvidenceRef[]; confidence?: number };
  paid_acquisition: { summary: string; evidence_refs?: EvidenceRef[]; confidence?: number };
  business_results: { summary: string; evidence_refs?: EvidenceRef[]; confidence?: number };
  summary: string;
}
