export interface Workspace {
  id: string;
  name: string;
  description: string;
  owner_id: string;
  created_at: string;
}

export interface Document {
  id: string;
  workspace_id: string;
  filename: string;
  source_type: string;
  content_type: string;
  status: "processing" | "ready" | "failed";
  error: string | null;
  num_chunks: number;
  num_pages: number;
  media_url: string | null;
  size_bytes: number;
  created_at: string;
}

export interface Dataset {
  id: string;
  workspace_id: string;
  filename: string;
  content_type: string;
  status: "processing" | "ready" | "failed";
  error: string | null;
  num_rows: number;
  columns: { name: string; dtype: string }[];
  created_at: string;
}

export interface MediaAsset {
  id: string;
  workspace_id: string;
  kind: "image" | "audio" | "file";
  filename: string;
  url: string;
  transcript: string | null;
  analysis: Record<string, unknown> | null;
  size_bytes: number;
  created_at: string;
}

export interface Investigation {
  id: string;
  workspace_id: string;
  conversation_id: string;
  question: string;
  answer: string;
  capabilities: string[];
  citations: Citation[];
  charts: Chart[];
  evidence: Evidence[];
  confidence: number | null;
  model_runs: ModelRun[];
  tool_calls: number;
  latency_ms: number;
  created_at: string;
}

export interface Citation {
  chunk_id: string;
  document_id: string;
  document_name: string;
  source_type: string;
  page: number | null;
  section: string | null;
  snippet: string;
  score: number;
  media_url: string | null;
}

export interface Evidence {
  kind: "document" | "data" | "vision" | "audio";
  source_name: string;
  summary: string;
  citation: Citation | null;
  chart: Chart | null;
  media_url: string | null;
}

export interface Chart {
  chart_type: string;
  title: string;
  x_label: string;
  y_label: string;
  labels: string[];
  series: { name: string; values: number[] }[];
  caption: string;
}

export interface ModelRun {
  provider: string;
  model: string;
  task: string;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
}

export interface Conversation {
  id: string;
  workspace_id: string;
  title: string;
  updated_at: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  attachment_ids: string[];
  citations: Citation[];
  charts: Chart[];
  confidence: number | null;
  investigation_id: string | null;
  created_at: string;
}

export interface EvalRun {
  id: string;
  workspace_id: string;
  status: string;
  num_cases: number;
  retrieval_recall_at_5: number | null;
  retrieval_mrr: number | null;
  answer_correctness: number | null;
  faithfulness: number | null;
  citation_accuracy: number | null;
  avg_latency_ms: number | null;
  created_at: string;
}

export interface TraceRun {
  id: string;
  workspace_id: string;
  investigation_id: string;
  trace_id: string;
  provider: string;
  model: string;
  task: string;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  created_at: string;
}
