import type { ContentSchema, FinalArtifact } from "../../types";
import type { RawSseEvent, WorkflowStatusResponse } from "./contracts";
import type { NormalizedEvent } from "./types";

function createSyntheticArtifact(event: RawSseEvent): FinalArtifact {
  return {
    kind: "content",
    mission_id: "",
    validation_passed: true,
    governance_report: null,
    artifact_uri: null,
    html_artifact: typeof event.html_artifact === "string" ? event.html_artifact : null,
    schema_data: (event.schema_data as ContentSchema | undefined) ?? null,
    skills_used: [],
    brand_dna_version: "",
    answer: null,
    error_message: null,
  };
}

export function normalizeSseEvent(event: RawSseEvent): NormalizedEvent | null {
  switch (event.type) {
    case "submitted":
      if (!event.thread_id || !event.session_id) return null;
      return {
        kind: "run.submitted",
        threadId: event.thread_id,
        sessionId: event.session_id,
        executionMode: event.execution_mode ?? "direct",
      };
    case "workflow_started":
      if (!event.thread_id) return null;
      return { kind: "run.started", threadId: event.thread_id, runId: event.run_id };
    case "planning":
      if (!event.thread_id) return null;
      return { kind: "run.progress", threadId: event.thread_id, label: "Planning execution strategy...", node: event.node, status: event.status };
    case "evidence_ready":
      if (!event.thread_id) return null;
      return { kind: "run.progress", threadId: event.thread_id, label: "GraphRAG: Evidence retrieved", node: event.node, status: event.status };
    case "content_ready":
      if (!event.thread_id) return null;
      return { kind: "run.progress", threadId: event.thread_id, label: "Vangogh: Content generated", node: event.node, status: event.status };
    case "signal_sent":
      if (!event.thread_id) return null;
      return { kind: "run.progress", threadId: event.thread_id, label: "Signal sent to workflow", node: event.node, status: event.status };
    case "hitl_required":
      if (!event.thread_id) return null;
      return { kind: "run.blocked.hitl", threadId: event.thread_id, agentNode: typeof event.node === "string" ? event.node : "content_node", questions: Array.isArray(event.questions) ? event.questions : [] };
    case "resuming":
      if (!event.thread_id) return null;
      return { kind: "run.resuming", threadId: event.thread_id };
    case "governance":
      if (!event.thread_id) return null;
      return { kind: "run.governance.completed", threadId: event.thread_id, governanceReport: (event.governance_report as typeof event.governance_report) ?? null };
    case "complete":
      if (!event.thread_id) return null;
      return { kind: "run.completed", threadId: event.thread_id, finalArtifact: event.final_artifact ?? null };
    case "regen_started":
      if (!event.thread_id) return null;
      return { kind: "run.regeneration.started", threadId: event.thread_id };
    case "regen_complete":
      if (!event.thread_id) return null;
      return { kind: "run.regeneration.completed", threadId: event.thread_id, finalArtifact: createSyntheticArtifact(event) };
    case "error":
      return { kind: "run.failed", threadId: event.thread_id ?? "", message: event.message ?? "Unknown workflow error" };
    default:
      return null;
  }
}

export function normalizeStatus(status: WorkflowStatusResponse): NormalizedEvent {
  return {
    kind: "run.rehydrated",
    threadId: status.thread_id,
    finalArtifact: status.final_artifact,
    status: status.status,
    currentNode: status.current_node,
    hitlRequired: status.hitl_required,
    hitlQuestions: status.hitl_questions,
    updatedAt: status.updated_at,
  };
}
