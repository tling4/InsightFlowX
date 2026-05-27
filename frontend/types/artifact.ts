export type ArtifactType =
  | "collection_raw"
  | "feature_matrix"
  | "pricing_comparison"
  | "user_sentiment"
  | "swot_analysis"
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
    feature_name: string;
    products: Record<string, string>;
  }>;
}

export interface PricingComparison {
  plans: Array<{
    product: string;
    tiers: Array<{ name: string; price: number; highlights: string[] }>;
  }>;
  summary: string;
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
