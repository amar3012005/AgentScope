export interface FinalArtifact {
  kind: "content" | "evidence_only" | "error";
  mission_id: string;
  validation_passed: boolean;
  governance_report: GovernanceReport | null;
  artifact_uri: string | null;
  html_artifact: string | null;
  schema_data: ContentSchema | null;
  skills_used: string[];
  brand_dna_version: string;
  answer: string | null;
  error_message: string | null;
}

export interface GovernanceReport {
  mission_id: string;
  validation_passed: boolean;
  policy_checks: PolicyCheck[];
  violations: string[];
  approved_output: string | null;
  timestamp: string;
}

export interface PolicyCheck {
  rule: string;
  passed: boolean;
  detail: string;
}

export interface ContentSchema {
  strategic_pillars: string[];
  kpis: string[];
  target_audience: string;
  vision_statement: string;
  timeline: string;
}

export interface SSEEvent {
  type: string;
  normalized_type?: string;
  event_ts?: string;
  timestamp?: string | number;
  thread_id?: string;
  session_id?: string;
  run_id?: string;
  execution_mode?: string;
  node?: string;
  status?: string;
  questions?: string[];
  message?: string;
  final_artifact?: FinalArtifact;
  result?: Record<string, unknown>;
  governance_report?: GovernanceReport;
  content_draft?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface WorkflowStatus {
  thread_id: string;
  execution_mode: string;
  status: string;
  current_node: string;
  hitl_required: boolean;
  hitl_questions: string[];
  error_message: string;
  final_artifact: FinalArtifact | null;
  updated_at: string;
}

export type TimelineStepStatus = "active" | "done" | "blocked" | "warning" | "failed";

export interface Message {
  id: string;
  sender: "user" | "assistant" | "system";
  text: string;
  htmlContent?: string;
  agentName?: string;
  timestamp: number;
}
