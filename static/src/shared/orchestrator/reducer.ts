import { createId, labelForEvent, statusForEvent, timelineDataForEvent } from "./timeline";
import type {
  ArtifactState,
  ContentSchema,
  ChatMessage,
  GovernanceState,
  HitlState,
  OrchestratorHydration,
  OrchestratorState,
  RoutingDecisionState,
  SectionFragment,
  SSEEvent,
  SchemaState,
  TimelineEntry,
  UploadState,
  WorkflowStatusResponse,
} from "./types";

function eventType(event: SSEEvent): string {
  return event.normalized_type || event.type;
}

export type OrchestratorAction =
  | { type: "hydrate"; payload: OrchestratorHydration }
  | { type: "set-session"; sessionId: string }
  | { type: "set-thread"; threadId: string }
  | { type: "set-workflow-mode"; workflowMode: OrchestratorState["workflowMode"] }
  | { type: "set-processing"; key: "isSubmitting" | "isResuming" | "isRegenerating"; value: boolean }
  | { type: "add-message"; message: ChatMessage }
  | { type: "append-timeline"; entry: TimelineEntry }
  | { type: "upsert-timeline"; label: string; status: TimelineEntry["status"]; timestamp?: number }
  | { type: "set-hitl"; payload: Partial<HitlState> }
  | { type: "set-schema"; payload: Partial<SchemaState> }
  | { type: "set-governance"; payload: Partial<GovernanceState> }
  | { type: "set-routing"; payload: Partial<RoutingDecisionState> }
  | { type: "set-artifact"; payload: Partial<ArtifactState> }
  | { type: "set-status"; payload: WorkflowStatusResponse | null }
  | { type: "set-workflows"; workflows: OrchestratorState["workflows"] }
  | { type: "set-active-node"; node: string }
  | { type: "set-last-error"; message: string }
  | { type: "set-uploads"; uploads: UploadState[] }
  | { type: "upsert-upload"; upload: UploadState }
  | { type: "update-upload"; id: string; patch: Partial<UploadState> }
  | { type: "clear-run" }
  | { type: "apply-event"; event: SSEEvent };

export function createInitialState(tenantId: string): OrchestratorState {
  const sessionId = crypto.randomUUID();
  return {
    tenantId,
    sessionId,
    threadId: "",
    runId: "",
    workflowMode: "standard",
    isSubmitting: false,
    isResuming: false,
    isRegenerating: false,
    activeNode: "",
    status: null,
    workflows: [],
    messages: [],
    timeline: [],
    hitl: {
      open: false,
      questions: [],
      threadId: "",
      agentNode: "content_node",
      submitting: false,
    },
    schema: {
      open: false,
      draft: null,
      submitting: false,
    },
    governance: {
      report: null,
      open: false,
    },
    artifact: {
      html: "",
      title: "",
      visible: false,
      source: "none",
      loading: false,
      loadingLabel: "",
      sections: [],
      viewMode: "preview",
      artifactKind: "",
      totalSections: 0,
      currentSlide: 0,
      slideTitles: [],
    },
    routing: {
      open: false,
      primaryAgent: "",
      selectedAgents: [],
      helperAgents: [],
      routeMode: "",
      requestedCapability: "",
      reasoning: "",
      executionPlan: [],
      liveAgents: [],
    },
    uploads: [],
    lastError: "",
  };
}

function upsertTimeline(
  timeline: TimelineEntry[],
  label: string,
  status: TimelineEntry["status"],
  detail?: string,
  data?: Record<string, string>,
  timestamp?: number
): TimelineEntry[] {
  const entryTimestamp = typeof timestamp === "number" ? timestamp : Date.now();
  const existingIndex = timeline.findIndex((entry) => entry.label === label);
  const nextEntry: TimelineEntry = {
    id: existingIndex >= 0 ? timeline[existingIndex].id : createId(),
    label,
    status,
    timestamp: entryTimestamp,
    detail,
    data,
  };

  if (existingIndex >= 0) {
    const next = [...timeline];
    next[existingIndex] = nextEntry;
    return next;
  }

  return [...timeline, nextEntry];
}

function appendMessage(
  messages: ChatMessage[],
  message: Omit<ChatMessage, "id" | "createdAt">,
  createdAt?: number
): ChatMessage[] {
  return [
    ...messages,
    {
      id: createId(),
      createdAt: typeof createdAt === "number" ? createdAt : Date.now(),
      ...message,
    },
  ];
}

function parseEventTimestamp(event: SSEEvent): number | undefined {
  const raw = event.event_ts ?? event.timestamp;
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return raw;
  }
  if (typeof raw === "string" && raw.trim()) {
    const parsed = Date.parse(raw);
    if (!Number.isNaN(parsed)) {
      return parsed;
    }
  }
  return undefined;
}

function eventMessage(event: SSEEvent): Omit<ChatMessage, "id" | "createdAt"> | null {
  const type = eventType(event);
  const result = (event.result ?? {}) as Record<string, unknown>;
  switch (type) {
    case "workflow_started":
      return {
        role: "event",
        agentName: "BLAIQ Core",
        kind: "status",
        text: "Workflow started.",
        meta: event.execution_mode ? { mode: String(event.execution_mode) } : undefined,
      };
    case "routing_decision": {
      const strategy = (event.strategy ?? {}) as Record<string, unknown>;
      const primary = String(strategy.primary_agent || "");
      const plan = Array.isArray(event.strategy_execution_plan)
        ? event.strategy_execution_plan.map((x) => String(x)).join(" → ")
        : "";
      return {
        role: "event",
        agentName: "Strategist",
        kind: "routing",
        text: "Core classified the request and selected the execution path.",
        meta: {
          workflow: Array.isArray(event.strategy_execution_plan) && event.strategy_execution_plan.includes("content")
            ? "creation"
            : "analysis",
          ...(primary ? { primary } : {}),
          ...(plan ? { flow: plan } : {}),
        },
        bullets: [
          Array.isArray(strategy.helper_agents) && strategy.helper_agents.length > 0
            ? `Helpers: ${strategy.helper_agents.map((x) => String(x)).join(", ")}`
            : "Helpers: none",
          Array.isArray(strategy.selected_agents) && strategy.selected_agents.length > 0
            ? `Agents: ${strategy.selected_agents.map((x) => String(x)).join(", ")}`
            : "",
        ].filter(Boolean),
      };
    }
    case "planning": {
      const plan = Array.isArray(result.execution_plan)
        ? (result.execution_plan as unknown[]).map((p) => String(p)).join(" → ")
        : "";
      return {
        role: "event",
        agentName: "Planner",
        kind: "status",
        text: plan
          ? `Planner decided execution path: ${plan}.`
          : "Planner is analyzing your request and selecting execution path.",
      };
    }
    case "evidence_refreshed":
      return {
        role: "event",
        agentName: "GraphRAG",
        kind: "evidence",
        text: "GraphRAG refreshed the evidence set using your clarifications.",
      };
    case "evidence_summary":
    case "evidence_ready":
      return {
        role: "event",
        agentName: "GraphRAG",
        kind: "evidence",
        text: "GraphRAG assembled the working evidence set for the run.",
        meta: (() => {
          const summary = (event.result ?? {}) as Record<string, unknown>;
          const chunks =
            typeof summary.chunks_retrieved === "number"
              ? summary.chunks_retrieved
              : typeof summary.chunk_count === "number"
                ? summary.chunk_count
                : null;

          const meta: Record<string, string> = {};
          if (event.node) {
            meta.node = String(event.node);
          }
          if (chunks !== null) {
            meta.chunks = String(chunks);
          }
          return Object.keys(meta).length > 0 ? meta : undefined;
        })(),
      };
    case "rendering_started":
    case "artifact_type_resolved":
      return {
        role: "event",
        agentName: "Vangogh",
        kind: "rendering",
        text: "Vangogh started rendering the artifact.",
      };
    case "section_started":
      return {
        role: "event",
        agentName: "Vangogh",
        kind: "rendering",
        text: "Vangogh is rendering the next section.",
        meta: {
          ...(typeof (event as Record<string, unknown>).section_label === "string"
            ? { section: String((event as Record<string, unknown>).section_label) }
            : {}),
        },
      };
    case "section_ready":
      return null;
    case "artifact_ready":
    case "artifact_composed":
    case "content_ready":
      return {
        role: "event",
        agentName: "Vangogh",
        kind: "artifact_intro",
        text: "Vangogh has a draft ready. The preview rail is now live.",
      };
    case "hitl_required":
      return {
        role: "event",
        agentName: "Vangogh",
        kind: "hitl",
        text: "A few structured clarifications are needed before final rendering.",
        meta: {
          questions: String((event.questions ?? []).length),
        },
        bullets: (event.questions ?? []).map((question) => String(question)),
      };
    case "signal_sent":
      return {
        role: "event",
        agentName: "BLAIQ Core",
        kind: "status",
        text: "Your HITL answers were sent. Resuming workflow.",
      };
    case "resuming":
      return {
        role: "event",
        agentName: "BLAIQ Core",
        kind: "status",
        text: "Workflow resumed from HITL checkpoint.",
      };
    case "governance": {
      const report = event.governance_report;
      if (!report) {
        return {
          role: "event",
          agentName: "Governance",
          kind: "governance",
          text: "Running governance checks.",
        };
      }
      return {
        role: "event",
        agentName: "Governance",
        kind: "governance",
        text: report.validation_passed
          ? `Governance passed (${report.policy_checks.length} checks).`
          : `Governance found ${report.violations.length} violation(s).`,
        meta: {
          checks: String(report.policy_checks.length),
          violations: String(report.violations.length),
          outcome: report.validation_passed ? "passed" : "attention needed",
        },
      };
    }
    case "complete": {
      const artifact = event.final_artifact;
      if (!artifact) {
        return {
          role: "event",
          agentName: "BLAIQ Core",
          kind: "status",
          text: "Workflow complete.",
        };
      }
      if (artifact.kind === "content") {
        return {
          role: "event",
          agentName: "Vangogh",
          kind: "artifact_intro",
          text: "The artifact is ready. Review the preview, schema, and governance tabs.",
        };
      }
      if (artifact.kind === "evidence_only") {
        return {
          role: "event",
          agentName: "GraphRAG",
          kind: "evidence",
          text: "Workflow complete. Returned evidence-backed answer.",
        };
      }
      return {
        role: "event",
        agentName: "BLAIQ Core",
        kind: "status",
        text: artifact.error_message || "Workflow complete with error artifact.",
      };
    }
    case "regen_complete":
      return {
        role: "event",
        agentName: "Vangogh",
        kind: "artifact_intro",
        text: "Regeneration complete. The preview was refreshed from your schema edits.",
      };
    default:
      return null;
  }
}

function applyWorkflowStatus(
  state: OrchestratorState,
  payload: WorkflowStatusResponse | null
): Partial<OrchestratorState> {
  if (!payload) {
    return { status: null };
  }

  return {
    status: payload,
    threadId: payload.thread_id || state.threadId,
    activeNode: payload.current_node || state.activeNode,
    artifact: payload.final_artifact
      ? {
          html:
            payload.final_artifact.governance_report?.approved_output ||
            payload.final_artifact.html_artifact ||
            "",
          title: "Stored artifact",
          visible: Boolean(
            payload.final_artifact.governance_report?.approved_output ||
              payload.final_artifact.html_artifact
          ),
          source: "status",
          loading: false,
          loadingLabel: "",
        }
      : state.artifact,
  };
}

function applyEvent(state: OrchestratorState, event: SSEEvent): Partial<OrchestratorState> {
  const type = eventType(event);
  const label = labelForEvent(event);
  const status = statusForEvent(event);
  const eventTimestamp = parseEventTimestamp(event);
  const contentDraft = (event.content_draft ?? event.result ?? {}) as Record<string, unknown>;

  const next: Partial<OrchestratorState> = {};

  if (event.thread_id) {
    next.threadId = event.thread_id;
  }
  if (event.session_id) {
    next.sessionId = event.session_id;
  }
  if (event.run_id) {
    next.runId = event.run_id;
  }
  if (event.execution_mode) {
    next.workflowMode = event.execution_mode as OrchestratorState["workflowMode"];
  }
  if (event.node) {
    next.activeNode = event.node;
  }

  switch (type) {
    case "submitted":
      next.isSubmitting = true;
      break;
    case "workflow_started":
      next.isSubmitting = true;
      break;
    case "planning":
      next.isSubmitting = true;
      break;
    case "evidence_summary":
    case "evidence_ready":
      if (state.routing.executionPlan.includes("content")) {
        next.artifact = {
          ...state.artifact,
          visible: true,
          loading: true,
          loadingLabel: "Vangogh is extracting the narrative structure from the evidence.",
        };
      }
      break;
    case "evidence_refreshed":
      next.artifact = {
        ...state.artifact,
        visible: true,
        loading: true,
        loadingLabel: "GraphRAG is refreshing the evidence with your answers.",
      };
      break;
    case "rendering_started":
    case "artifact_type_resolved":
      next.artifact = {
        ...state.artifact,
        artifactKind: (event as Record<string, unknown>).kind as string || state.artifact.artifactKind || "",
        totalSections: (event as Record<string, unknown>).total_sections as number || state.artifact.totalSections || 0,
        sections: type === "artifact_type_resolved" ? [] : state.artifact.sections,
        visible: true,
        loading: true,
        loadingLabel:
          type === "artifact_type_resolved"
            ? `Preparing ${(event as Record<string, unknown>).kind || "artifact"} (${(event as Record<string, unknown>).total_sections || 0} sections)`
            : "Vangogh is rendering the artifact.",
      };
      break;
    case "artifact_ready":
    case "artifact_composed":
    case "content_ready":
      next.artifact = {
        ...state.artifact,
        visible: true,
        loading: false,
        loadingLabel: "",
      };
      break;
    case "hitl_required":
      next.hitl = {
        open: true,
        questions: event.questions ?? [],
        threadId: event.thread_id ?? state.threadId,
        agentNode: event.node || "content_node",
        submitting: false,
      };
      next.isSubmitting = false;
      next.isResuming = false;
      next.artifact = {
        ...state.artifact,
        visible: true,
        loading: false,
        loadingLabel: "Waiting for your answers before final composition.",
      };
      break;
    case "signal_sent":
      next.hitl = {
        ...state.hitl,
        open: false,
        submitting: false,
      };
      next.isResuming = true;
      next.artifact = {
        ...state.artifact,
        visible: true,
        loading: true,
        loadingLabel: "Vangogh is refreshing evidence and rebuilding the composition.",
      };
      break;
    case "resuming":
      next.isResuming = true;
      break;
    case "governance":
      next.governance = {
        report: event.governance_report ?? null,
        open: true,
      };
      break;
    case "complete":
      next.isSubmitting = false;
      next.isResuming = false;
      next.isRegenerating = false;
      next.hitl = {
        ...state.hitl,
        open: false,
        submitting: false,
      };
      next.schema = {
        ...state.schema,
        submitting: false,
      };
      next.artifact = {
        ...state.artifact,
        loading: false,
        loadingLabel: "",
      };
      break;
    case "error":
      next.isSubmitting = false;
      next.isResuming = false;
      next.isRegenerating = false;
      next.hitl = {
        ...state.hitl,
        open: false,
        submitting: false,
      };
      next.lastError = event.message || "Unknown error";
      next.artifact = {
        ...state.artifact,
        loading: false,
        loadingLabel: "",
      };
      break;
    case "regen_complete":
      next.isRegenerating = false;
      next.schema = {
        ...state.schema,
        submitting: false,
      };
      next.artifact = {
        ...state.artifact,
        loading: false,
        loadingLabel: "",
      };
      break;
    case "section_started":
      next.artifact = {
        ...state.artifact,
        loading: true,
        loadingLabel: `Rendering section ${((event as Record<string, unknown>).section_index as number || 0) + 1}/${state.artifact.totalSections || "?"}: ${(event as Record<string, unknown>).section_label || ""}`,
      };
      break;
    case "section_ready": {
      const sectionIndex = (event as Record<string, unknown>).section_index as number ?? 0;
      const totalSections = state.artifact.totalSections || 1;
      const newSection: SectionFragment = {
        sectionId: (event as Record<string, unknown>).section_id as string || "",
        sectionIndex,
        htmlFragment: (event as Record<string, unknown>).html_fragment as string || "",
        sectionData: (event as Record<string, unknown>).section_data as Record<string, unknown> || {},
        label: (event as Record<string, unknown>).section_label as string || "",
      };
      next.artifact = {
        ...state.artifact,
        sections: [...(state.artifact.sections || []), newSection],
        loading: sectionIndex + 1 < totalSections,
        loadingLabel: sectionIndex + 1 < totalSections
          ? `Rendering section ${sectionIndex + 2}/${totalSections}`
          : "Composing final artifact...",
      };
      break;
    }
    case "slide_metadata":
      next.artifact = {
        ...state.artifact,
        slideTitles: Array.isArray((event as Record<string, unknown>).slide_titles)
          ? ((event as Record<string, unknown>).slide_titles as string[])
          : [],
      };
      break;
    default:
      break;
  }

  if (label && status) {
    const { detail, data } = timelineDataForEvent(event);
    next.timeline = upsertTimeline(
      state.timeline,
      label,
      status,
      detail,
      data,
      eventTimestamp
    );
  }

  const finalArtifact = event.final_artifact;
  const htmlArtifact =
    typeof contentDraft.html_artifact === "string"
      ? contentDraft.html_artifact
      : typeof finalArtifact?.html_artifact === "string"
        ? finalArtifact.html_artifact
        : typeof event.html_artifact === "string"
          ? event.html_artifact
          : "";

  if (type === "submitted") {
    next.messages = appendMessage(state.messages, {
      role: "system",
      text: "Workflow submitted.",
      agentName: "Orchestrator",
    }, eventTimestamp);
  }

  const liveEventMessage = eventMessage(event);
  if (liveEventMessage) {
    next.messages = appendMessage(next.messages ?? state.messages, liveEventMessage, eventTimestamp);
  }

  if (type === "error") {
    next.messages = appendMessage(state.messages, {
      role: "system",
      text: `Error: ${event.message || "Unknown error"}`,
      agentName: "Orchestrator",
    }, eventTimestamp);
  }

  if (type === "complete") {
    if (finalArtifact?.kind === "content") {
      const html =
        finalArtifact.governance_report?.approved_output ||
        finalArtifact.html_artifact ||
        "";
      if (html) {
        next.artifact = {
          html,
          title: "Final artifact",
          visible: true,
          source: "complete",
          loading: false,
          loadingLabel: "",
        };
      }
    } else if (finalArtifact?.kind === "evidence_only" && finalArtifact.answer) {
      next.messages = appendMessage(state.messages, {
        role: "assistant",
        text: finalArtifact.answer,
        agentName: "GraphRAG",
      }, eventTimestamp);
    } else if (finalArtifact?.kind === "error" && finalArtifact.error_message) {
      next.messages = appendMessage(state.messages, {
        role: "system",
        text: finalArtifact.error_message,
        agentName: "Orchestrator",
      }, eventTimestamp);
    }
  }

  if (type === "content_ready" || type === "artifact_ready" || type === "artifact_composed") {
    const schemaData = contentDraft.schema_data as ContentSchema | undefined;

    if (htmlArtifact) {
      next.artifact = {
        html: htmlArtifact,
        title: "Generated artifact",
        visible: true,
        source: "content_ready",
        loading: false,
        loadingLabel: "",
      };
    }
    if (schemaData) {
      next.schema = {
        open: true,
        draft: schemaData,
        submitting: false,
      };
    }
  }

  if (type === "routing_decision") {
    const strategy = (event.strategy ?? {}) as Record<string, unknown>;
    const liveAgents = Array.isArray(event.live_agents)
      ? event.live_agents
          .map((item) => {
            if (!item || typeof item !== "object") {
              return null;
            }
            const agent = item as Record<string, unknown>;
            return {
              name: typeof agent.name === "string" ? agent.name : "",
              isLive: Boolean(agent.is_live),
              capabilities: Array.isArray(agent.capabilities)
                ? agent.capabilities.map((value) => String(value))
                : [],
            };
          })
          .filter((item): item is { name: string; isLive: boolean; capabilities: string[] } =>
            Boolean(item && item.name)
          )
      : [];
    next.routing = {
      open: true,
      primaryAgent: typeof strategy.primary_agent === "string" ? strategy.primary_agent : "",
      selectedAgents: Array.isArray(strategy.selected_agents)
        ? strategy.selected_agents.map((value) => String(value))
        : [],
      helperAgents: Array.isArray(strategy.helper_agents)
        ? strategy.helper_agents.map((value) => String(value))
        : [],
      routeMode: typeof strategy.route_mode === "string" ? strategy.route_mode : "",
      requestedCapability:
        typeof strategy.requested_capability === "string"
          ? strategy.requested_capability
          : "",
      reasoning: typeof strategy.reasoning === "string" ? strategy.reasoning : "",
      executionPlan: Array.isArray(event.strategy_execution_plan)
        ? event.strategy_execution_plan.map((value) => String(value))
        : [],
      liveAgents,
    };
  }

  if (type === "regen_complete") {
    if (htmlArtifact) {
      next.artifact = {
        html: htmlArtifact,
        title: "Regenerated artifact",
        visible: true,
        source: "regenerated",
        loading: false,
        loadingLabel: "",
      };
    }
  }

  return next;
}

export function orchestratorReducer(
  state: OrchestratorState,
  action: OrchestratorAction
): OrchestratorState {
  switch (action.type) {
    case "hydrate":
      return {
        ...state,
        ...action.payload,
        messages: action.payload.messages ?? state.messages,
        uploads: action.payload.uploads ?? state.uploads,
      };
    case "set-session":
      return { ...state, sessionId: action.sessionId };
    case "set-thread":
      return { ...state, threadId: action.threadId };
    case "set-workflow-mode":
      return { ...state, workflowMode: action.workflowMode };
    case "set-processing":
      return { ...state, [action.key]: action.value } as OrchestratorState;
    case "add-message":
      return { ...state, messages: [...state.messages, action.message] };
    case "append-timeline":
      return { ...state, timeline: [...state.timeline, action.entry] };
    case "upsert-timeline":
      return {
        ...state,
        timeline: upsertTimeline(state.timeline, action.label, action.status, undefined, undefined, action.timestamp),
      };
    case "set-hitl":
      return { ...state, hitl: { ...state.hitl, ...action.payload } };
    case "set-schema":
      return { ...state, schema: { ...state.schema, ...action.payload } };
    case "set-governance":
      return { ...state, governance: { ...state.governance, ...action.payload } };
    case "set-routing":
      return { ...state, routing: { ...state.routing, ...action.payload } };
    case "set-artifact":
      return { ...state, artifact: { ...state.artifact, ...action.payload } };
    case "set-status":
      return { ...state, ...applyWorkflowStatus(state, action.payload) };
    case "set-workflows":
      return { ...state, workflows: action.workflows };
    case "set-active-node":
      return { ...state, activeNode: action.node };
    case "set-last-error":
      return { ...state, lastError: action.message };
    case "set-uploads":
      return { ...state, uploads: action.uploads };
    case "upsert-upload": {
      const next = [...state.uploads];
      const index = next.findIndex((item) => item.id === action.upload.id);
      if (index >= 0) {
        next[index] = action.upload;
      } else {
        next.unshift(action.upload);
      }
      return { ...state, uploads: next };
    }
    case "update-upload":
      return {
        ...state,
        uploads: state.uploads.map((upload) =>
          upload.id === action.id ? { ...upload, ...action.patch } : upload
        ),
      };
    case "clear-run":
      return {
        ...state,
        messages: [],
        threadId: "",
        runId: "",
        isSubmitting: false,
        isResuming: false,
        isRegenerating: false,
        activeNode: "",
        status: null,
        timeline: [],
        hitl: {
          open: false,
          questions: [],
          threadId: "",
          agentNode: "content_node",
          submitting: false,
        },
        schema: {
          open: false,
          draft: null,
          submitting: false,
        },
        governance: {
          report: null,
          open: false,
        },
        artifact: {
          html: "",
          title: "",
          visible: false,
          source: "none",
          sections: [],
          viewMode: "preview",
          artifactKind: "",
          totalSections: 0,
          currentSlide: 0,
          slideTitles: [],
        },
        routing: {
          open: false,
          primaryAgent: "",
          selectedAgents: [],
          helperAgents: [],
          routeMode: "",
          requestedCapability: "",
          reasoning: "",
          executionPlan: [],
          liveAgents: [],
        },
        lastError: "",
      };
    case "apply-event":
      return {
        ...state,
        ...applyEvent(state, action.event),
      };
    default:
      return state;
  }
}
