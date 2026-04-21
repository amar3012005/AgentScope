import type { SSEEvent, TimelineStepStatus } from "./types";

function eventType(event: SSEEvent): string {
  return event.normalized_type || event.type;
}

export function createId(): string {
  return crypto.randomUUID();
}

export function formatTimelineTime(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function labelForEvent(event: SSEEvent): string | null {
  switch (eventType(event)) {
    case "submitted":
      return "Workflow submitted";
    case "workflow_started":
      return "Workflow started";
    case "routing_decision":
      return "Agent routing decided";
    case "planning":
      return "Planning workflow";
    case "evidence_summary":
    case "evidence_ready":
      return "GraphRAG: Evidence retrieved";
    case "evidence_refreshed":
      return "GraphRAG: Evidence refreshed";
    case "rendering_started":
    case "artifact_type_resolved":
      return "Vangogh: Rendering started";
    case "section_started":
      return "Vangogh: Section rendering";
    case "section_ready":
      return "Vangogh: Section ready";
    case "artifact_ready":
    case "content_ready":
    case "artifact_composed":
      return "Vangogh: Content generated";
    case "hitl_required":
      return "Paused - waiting for input";
    case "signal_sent":
      return "Signal sent to workflow";
    case "resuming":
      return "Resuming workflow";
    case "governance":
      return "Governance checks";
    case "complete":
      return "Complete";
    case "error":
      return "Error";
    case "regen_complete":
      return "Regenerated content";
    default:
      return null;
  }
}

export function statusForEvent(event: SSEEvent): TimelineStepStatus | null {
  switch (eventType(event)) {
    case "submitted":
    case "workflow_started":
    case "routing_decision":
    case "evidence_summary":
    case "evidence_ready":
    case "evidence_refreshed":
    case "artifact_ready":
    case "content_ready":
    case "signal_sent":
    case "governance":
    case "complete":
    case "regen_complete":
    case "section_ready":
    case "artifact_composed":
      return "done";
    case "planning":
    case "resuming":
    case "rendering_started":
    case "artifact_type_resolved":
    case "section_started":
      return "active";
    case "hitl_required":
      return "blocked";
    case "error":
      return "failed";
    default:
      return null;
  }
}

function asRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  return value as Record<string, unknown>;
}

function readNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function readChunkCount(event: SSEEvent): number | null {
  const eventRecord = event as Record<string, unknown>;
  const summary = asRecord((event.result as Record<string, unknown> | undefined)?.summary);
  return (
    readNumber(eventRecord.chunks_retrieved) ??
    readNumber(summary.chunks_retrieved) ??
    readNumber(summary.chunk_count) ??
    readNumber((event.result as Record<string, unknown> | undefined)?.chunks_retrieved)
  );
}

export function timelineDataForEvent(event: SSEEvent): {
  detail?: string;
  data?: Record<string, string>;
} {
  const type = eventType(event);
  const data: Record<string, string> = {};

  if (typeof event.node === "string" && event.node) {
    data.node = event.node;
  }
  if (typeof event.status === "string" && event.status) {
    data.status = event.status;
  }
  if (typeof event.thread_id === "string" && event.thread_id) {
    data.thread = event.thread_id.slice(0, 8);
  }
  if (typeof event.run_id === "string" && event.run_id) {
    data.run = event.run_id.slice(0, 8);
  }
  if (typeof event.session_id === "string" && event.session_id) {
    data.session = event.session_id.slice(0, 8);
  }
  if (typeof event.execution_mode === "string" && event.execution_mode) {
    data.mode = event.execution_mode;
  }

  if (type === "planning") {
    const result = asRecord(event.result);
    const executionPlan = Array.isArray(result.execution_plan) ? result.execution_plan.length : null;
    const keywords = Array.isArray(result.keywords) ? result.keywords.length : null;
    if (executionPlan !== null) {
      data.plan_steps = String(executionPlan);
    }
    if (keywords !== null) {
      data.keywords = String(keywords);
    }
  }

  if (type === "routing_decision") {
    const strategy = asRecord(event.strategy);
    if (typeof strategy.primary_agent === "string" && strategy.primary_agent) {
      data.primary = strategy.primary_agent;
    }
    if (Array.isArray(strategy.selected_agents)) {
      data.selected = String(strategy.selected_agents.length);
    }
    if (Array.isArray(event.strategy_execution_plan)) {
      data.plan_steps = String(event.strategy_execution_plan.length);
    }
  }

  if (type === "evidence_ready" || type === "evidence_summary" || type === "evidence_refreshed") {
    const chunkCount = readChunkCount(event);
    if (chunkCount !== null) {
      data.chunks = String(chunkCount);
    }
  }

  if (type === "hitl_required") {
    const questionCount = Array.isArray(event.questions) ? event.questions.length : 0;
    data.questions = String(questionCount);
  }

  if (
    type === "content_ready" ||
    type === "artifact_ready" ||
    type === "artifact_composed" ||
    type === "rendering_started" ||
    type === "artifact_type_resolved" ||
    type === "section_started" ||
    type === "section_ready"
  ) {
    const source = asRecord(event.content_draft);
    const schema = asRecord(source.schema_data);
    const kpis = Array.isArray(schema.kpis) ? schema.kpis.length : null;
    const pillars = Array.isArray(schema.strategic_pillars) ? schema.strategic_pillars.length : null;
    const sectionIndex = readNumber((event as Record<string, unknown>).section_index);
    const totalSections = readNumber((event as Record<string, unknown>).total_sections);
    if (kpis !== null) {
      data.kpis = String(kpis);
    }
    if (pillars !== null) {
      data.pillars = String(pillars);
    }
    if (typeof source.html_artifact === "string") {
      data.html = `${source.html_artifact.length.toLocaleString()} chars`;
    }
    if (sectionIndex !== null) {
      data.section = String(sectionIndex + 1);
    }
    if (totalSections !== null) {
      data.total_sections = String(totalSections);
    }
  }

  if (type === "governance") {
    const report = asRecord(event.governance_report);
    const checks = Array.isArray(report.policy_checks) ? report.policy_checks.length : 0;
    const violations = Array.isArray(report.violations) ? report.violations.length : 0;
    if (checks > 0) {
      data.policy_checks = String(checks);
    }
    data.violations = String(violations);
  }

  if (type === "complete" || type === "regen_complete") {
    const artifact = asRecord(event.final_artifact);
    if (typeof artifact.kind === "string") {
      data.artifact = artifact.kind;
    }
    if (typeof artifact.validation_passed === "boolean") {
      data.validation = artifact.validation_passed ? "passed" : "failed";
    }
  }

  if (type === "error" && typeof event.message === "string" && event.message) {
    data.error = event.message;
  }

  const detail =
    typeof event.message === "string" && event.message
      ? event.message
      : Object.keys(data).length > 0
        ? Object.entries(data)
            .slice(0, 3)
            .map(([key, value]) => `${key}: ${value}`)
            .join(" · ")
        : undefined;

  return {
    detail,
    data: Object.keys(data).length > 0 ? data : undefined,
  };
}
