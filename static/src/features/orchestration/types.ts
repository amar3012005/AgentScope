import type { ContentSchema, FinalArtifact, GovernanceReport } from "../../types";

export type ConnectionStatus = "idle" | "streaming" | "recovering" | "ready" | "error";
export type PaneTab = "timeline" | "artifact" | "schema" | "governance";
export type TimelineStatus = "active" | "done" | "blocked" | "warning" | "failed";

export interface TimelineEntry {
  id: string;
  label: string;
  status: TimelineStatus;
  timestamp: string;
  node?: string;
}

export interface WorkspaceMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  format: "text" | "markdown" | "status";
  timestamp: number;
  agentName?: string;
}

export interface HitlPrompt {
  threadId: string;
  agentNode: string;
  questions: string[];
  draftAnswers: Record<string, string>;
}

export interface UploadItem {
  id: string;
  filename: string;
  status: "uploading" | "ready" | "error";
  timestamp: number;
  message?: string;
}

export interface RunRecord {
  threadId: string;
  sessionId: string;
  workflowMode: string;
  executionMode: string;
  status: string;
  currentNode: string;
  userQuery: string;
  updatedAt: string;
  messages: WorkspaceMessage[];
  timeline: TimelineEntry[];
  finalArtifact: FinalArtifact | null;
  resolvedHtml: string;
  governanceReport: GovernanceReport | null;
  schemaDraft: ContentSchema | null;
  hitl: HitlPrompt | null;
  lastError: string;
}

export interface OrchestrationState {
  workspace: {
    tenantId: string;
    activeThreadId: string;
    activeSessionId: string;
    workflowMode: string;
  };
  runsById: Record<string, RunRecord>;
  history: {
    recentThreadIds: string[];
  };
  uploads: {
    items: UploadItem[];
  };
  ui: {
    sidebarCollapsed: boolean;
    activePane: PaneTab;
    schemaDrawerOpen: boolean;
    governanceDrawerOpen: boolean;
  };
  connection: {
    status: ConnectionStatus;
    pendingPrompt: string;
  };
}

export type NormalizedEvent =
  | { kind: "run.submitted"; threadId: string; sessionId: string; executionMode: string }
  | { kind: "run.started"; threadId: string; runId?: string }
  | { kind: "run.progress"; threadId: string; label: string; node?: string; status?: string }
  | { kind: "run.blocked.hitl"; threadId: string; agentNode: string; questions: string[] }
  | { kind: "run.resuming"; threadId: string }
  | { kind: "run.governance.completed"; threadId: string; governanceReport: GovernanceReport | null }
  | { kind: "run.completed"; threadId: string; finalArtifact: FinalArtifact | null }
  | { kind: "run.regeneration.started"; threadId: string }
  | { kind: "run.regeneration.completed"; threadId: string; finalArtifact: FinalArtifact }
  | { kind: "run.failed"; threadId: string; message: string }
  | { kind: "run.rehydrated"; threadId: string; finalArtifact: FinalArtifact | null; status: string; currentNode: string; hitlRequired: boolean; hitlQuestions: string[]; updatedAt: string };
