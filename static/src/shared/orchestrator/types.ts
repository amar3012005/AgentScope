import type {
  ContentSchema,
  FinalArtifact,
  GovernanceReport,
  SSEEvent,
  TimelineStepStatus,
  WorkflowStatus,
} from "../../types";

export type {
  ContentSchema,
  FinalArtifact,
  GovernanceReport,
  SSEEvent,
  TimelineStepStatus,
  WorkflowStatus,
};

export type WorkflowMode = "standard" | "deep_research" | "creative";

export type OrchestratorRuntimeStatus =
  | "queued"
  | "dispatching"
  | "running"
  | "blocked_on_user"
  | "resuming"
  | "complete"
  | "error"
  | string;

export interface SubmitWorkflowRequest {
  user_query: string;
  workflow_mode?: WorkflowMode;
  collection_name?: string;
  session_id?: string;
  use_template_engine?: boolean;
}

export interface ResumeWorkflowRequest {
  thread_id: string;
  agent_node?: string;
  answers: Record<string, string>;
}

export interface RegenerateWorkflowRequest {
  thread_id: string;
  patched_schema: ContentSchema;
  workflow_mode?: WorkflowMode;
}

export interface WorkflowSummary {
  workflow_id: string;
  run_id: string;
  status: string;
  start_time: string;
  thread_id?: string;
}

export interface WorkflowListResponse {
  workflows: WorkflowSummary[];
}

export interface UploadDocumentRequest {
  file: File;
  metadata?: Record<string, unknown> | string;
}

export interface UploadDocumentResponse {
  status: string;
  request_id: string;
  filename: string;
  file_size: number;
  processing_result?: Record<string, unknown> | null;
}

export interface WorkflowStatusResponse extends WorkflowStatus {
  run_id?: string;
  session_id?: string;
  workflow_mode?: WorkflowMode;
  collection_name?: string;
}

export interface OrchestratorStreamHandlers {
  onEvent: (event: SSEEvent) => void;
  onDone?: () => void;
  onError?: (error: Error) => void;
}

export interface TimelineEntry {
  id: string;
  label: string;
  status: TimelineStepStatus;
  timestamp: number;
  detail?: string;
  data?: Record<string, string>;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system" | "event";
  text: string;
  agentName?: string;
  kind?:
    | "default"
    | "status"
    | "routing"
    | "evidence"
    | "rendering"
    | "hitl"
    | "governance"
    | "artifact_intro";
  meta?: Record<string, string>;
  bullets?: string[];
  html?: string;
  createdAt: number;
}

export interface HitlState {
  open: boolean;
  questions: string[];
  threadId: string;
  agentNode: string;
  submitting: boolean;
}

export interface SchemaState {
  open: boolean;
  draft: ContentSchema | null;
  submitting: boolean;
}

export interface GovernanceState {
  report: GovernanceReport | null;
  open: boolean;
}

export interface SectionFragment {
  sectionId: string;
  sectionIndex: number;
  htmlFragment: string;
  sectionData: Record<string, unknown>;
  label: string;
}

export interface ArtifactState {
  html: string;
  title: string;
  visible: boolean;
  source: "none" | "content_ready" | "complete" | "regenerated" | "status";
  loading?: boolean;
  loadingLabel?: string;
  sections?: SectionFragment[];
  viewMode?: "preview" | "code" | "split";
  artifactKind?: string;
  totalSections?: number;
  currentSlide?: number;
  slideTitles?: string[];
  baseShellHtml?: string;
}

export interface UploadState {
  id: string;
  name: string;
  size: number;
  status: "queued" | "uploading" | "success" | "error";
  message?: string;
}

export interface LiveAgentState {
  name: string;
  isLive: boolean;
  capabilities: string[];
}

export interface RoutingDecisionState {
  open: boolean;
  primaryAgent: string;
  selectedAgents: string[];
  helperAgents: string[];
  routeMode: string;
  requestedCapability: string;
  reasoning: string;
  executionPlan: string[];
  liveAgents: LiveAgentState[];
}

export interface OrchestratorState {
  tenantId: string;
  sessionId: string;
  threadId: string;
  runId: string;
  workflowMode: WorkflowMode;
  isSubmitting: boolean;
  isResuming: boolean;
  isRegenerating: boolean;
  activeNode: string;
  status: WorkflowStatusResponse | null;
  workflows: WorkflowSummary[];
  messages: ChatMessage[];
  timeline: TimelineEntry[];
  hitl: HitlState;
  schema: SchemaState;
  governance: GovernanceState;
  artifact: ArtifactState;
  routing: RoutingDecisionState;
  uploads: UploadState[];
  lastError: string;
}

export interface OrchestratorHydration {
  threadId?: string;
  sessionId?: string;
  runId?: string;
  messages?: ChatMessage[];
  uploads?: UploadState[];
}

export interface SaveChatSnapshotRequest {
  thread_id?: string;
  session_id: string;
  run_id?: string;
  workflow_mode?: WorkflowMode;
  messages: ChatMessage[];
  timeline: TimelineEntry[];
  artifact?: ArtifactState;
  governance?: GovernanceState;
  schema?: SchemaState;
  status?: WorkflowStatusResponse | null;
}

export interface SaveChatSnapshotResponse {
  status: "saved";
  file_path: string;
  file_name: string;
}
