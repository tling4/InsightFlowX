export interface SourceRef {
  url: string;
  title: string;
  snippet: string;
  confidence: number;
}

export interface TraceLink {
  id: string;
  workflow_id: string;
  section_path: string;
  claim: string;
  source_url: string;
  source_title: string;
  confidence: number;
  is_verified: boolean;
  created_at: string;
}
