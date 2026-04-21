import type { ContentSchema, FinalArtifact, GovernanceReport, WorkflowStatus } from "../../types";

export interface SubmitRequest {
  tenant_id: string;
  user_query: string;
  workflow_mode: string;
  collection_name?: string;
  session_id?: string;
}

export interface ResumeRequest {
  thread_id: string;
  agent_node?: string;
  answers: Record<string, string>;
}

export interface RegenerateRequest {
  thread_id: string;
  patched_schema: ContentSchema;
  workflow_mode: string;
}

export interface WorkflowListItem {
  workflow_id: string;
  run_id?: string;
  status?: string;
  start_time?: string;
}

export interface WorkflowsResponse {
  workflows: WorkflowListItem[];
  note?: string;
  error?: string;
}

export interface UploadResponse {
  status: string;
  request_id: string;
  filename: string;
  file_size: number;
  processing_result?: Record<string, unknown>;
}

export interface RawSseEvent {
  type: string;
  thread_id?: string;
  session_id?: string;
  run_id?: string;
  execution_mode?: string;
  node?: string;
  status?: string;
  questions?: string[];
  message?: string;
  final_artifact?: FinalArtifact;
  governance_report?: GovernanceReport;
  html_artifact?: string;
  schema_data?: ContentSchema;
  result?: Record<string, unknown>;
  [key: string]: unknown;
}

export type WorkflowStatusResponse = WorkflowStatus;
