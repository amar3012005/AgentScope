import { createContext, useContext, useEffect, useMemo, useReducer } from "react";
import { CONFIG } from "../../config";
import type { ContentSchema, FinalArtifact, GovernanceReport } from "../../types";
import type { NormalizedEvent, OrchestrationState, RunRecord, UploadItem, WorkspaceMessage } from "./types";
import { artifactToHtml } from "./api";

type Action =
  | { type: "toggleSidebar" }
  | { type: "setActivePane"; pane: OrchestrationState["ui"]["activePane"] }
  | { type: "openSchemaDrawer"; open: boolean }
  | { type: "openGovernanceDrawer"; open: boolean }
  | { type: "setPendingPrompt"; prompt: string; workflowMode: string }
  | { type: "ingestEvent"; event: NormalizedEvent }
  | { type: "selectRun"; threadId: string }
  | { type: "setHitlDraft"; threadId: string; questionKey: string; value: string }
  | { type: "appendSystemMessage"; threadId: string; content: string }
  | { type: "hydrateWorkflows"; threadIds: string[] }
  | { type: "uploadStarted"; item: UploadItem }
  | { type: "uploadFinished"; id: string; status: UploadItem["status"]; message?: string }
  | { type: "setConnection"; status: OrchestrationState["connection"]["status"] };

const STORAGE_KEY = "blaiq_react_dashboard_state";

const initialState: OrchestrationState = {
  workspace: {
    tenantId: CONFIG.TENANT_ID,
    activeThreadId: "",
    activeSessionId: "",
    workflowMode: "standard",
  },
  runsById: {},
  history: {
    recentThreadIds: [],
  },
  uploads: {
    items: [],
  },
  ui: {
    sidebarCollapsed: false,
    activePane: "timeline",
    schemaDrawerOpen: false,
    governanceDrawerOpen: false,
  },
  connection: {
    status: "idle",
    pendingPrompt: "",
  },
};

function timelineEntry(label: string, status: RunRecord["timeline"][number]["status"], node?: string) {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    label,
    status,
    timestamp: new Date().toISOString(),
    node,
  };
}

function statusMessage(content: string, agentName?: string): WorkspaceMessage {
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    role: "system",
    content,
    format: "status",
    timestamp: Date.now(),
    agentName,
  };
}

function createRun(threadId: string, sessionId: string, workflowMode: string, prompt: string, executionMode: string): RunRecord {
  return {
    threadId,
    sessionId,
    workflowMode,
    executionMode,
    status: "queued",
    currentNode: "",
    userQuery: prompt,
    updatedAt: new Date().toISOString(),
    messages: prompt
      ? [
          {
            id: `${threadId}-user`,
            role: "user",
            content: prompt,
            format: "text",
            timestamp: Date.now(),
          },
        ]
      : [],
    timeline: [timelineEntry("Workflow submitted", "done")],
    finalArtifact: null,
    resolvedHtml: "",
    governanceReport: null,
    schemaDraft: null,
    hitl: null,
    lastError: "",
  };
}

function mergeRecent(history: string[], threadId: string) {
  return [threadId, ...history.filter((item) => item !== threadId)].slice(0, 24);
}

function reduceEvent(state: OrchestrationState, event: NormalizedEvent): OrchestrationState {
  switch (event.kind) {
    case "run.submitted": {
      const run = createRun(
        event.threadId,
        event.sessionId,
        state.workspace.workflowMode,
        state.connection.pendingPrompt,
        event.executionMode,
      );
      return {
        ...state,
        workspace: {
          ...state.workspace,
          activeThreadId: event.threadId,
          activeSessionId: event.sessionId,
        },
        runsById: { ...state.runsById, [event.threadId]: run },
        history: { recentThreadIds: mergeRecent(state.history.recentThreadIds, event.threadId) },
        connection: { status: "streaming", pendingPrompt: "" },
      };
    }
    case "run.started":
    case "run.progress":
    case "run.resuming":
    case "run.governance.completed":
    case "run.completed":
    case "run.regeneration.started":
    case "run.regeneration.completed":
    case "run.failed":
    case "run.blocked.hitl":
    case "run.rehydrated": {
      const threadId = event.threadId;
      const existing =
        state.runsById[threadId] ??
        createRun(threadId, state.workspace.activeSessionId || "", state.workspace.workflowMode, "", "direct");
      let next: RunRecord = existing;

      if (event.kind === "run.started") {
        next = {
          ...existing,
          status: "running",
          timeline: [...existing.timeline, timelineEntry("Workflow started", "done")],
          updatedAt: new Date().toISOString(),
        };
      }

      if (event.kind === "run.progress") {
        next = {
          ...next,
          status: event.status ?? "running",
          currentNode: event.node ?? next.currentNode,
          timeline: [...next.timeline, timelineEntry(event.label, "done", event.node)],
          updatedAt: new Date().toISOString(),
        };
      }

      if (event.kind === "run.resuming") {
        next = {
          ...next,
          status: "resuming",
          timeline: [...next.timeline, timelineEntry("Resuming with your answers...", "active")],
          hitl: null,
          updatedAt: new Date().toISOString(),
        };
      }

      if (event.kind === "run.blocked.hitl") {
        next = {
          ...next,
          status: "blocked_on_user",
          hitl: {
            threadId,
            agentNode: event.agentNode,
            questions: event.questions,
            draftAnswers: next.hitl?.draftAnswers ?? {},
          },
          timeline: [...next.timeline, timelineEntry("Paused — waiting for your input", "blocked", event.agentNode)],
          updatedAt: new Date().toISOString(),
        };
      }

      if (event.kind === "run.governance.completed") {
        next = {
          ...next,
          governanceReport: event.governanceReport,
          timeline: [
            ...next.timeline,
            timelineEntry(
              event.governanceReport?.validation_passed ? "Governance: All checks passed" : `Governance: ${event.governanceReport?.violations?.[0] ?? "Review needed"}`,
              event.governanceReport?.validation_passed ? "done" : "warning",
              "governance",
            ),
          ],
          updatedAt: new Date().toISOString(),
        };
      }

      if (event.kind === "run.completed" || event.kind === "run.regeneration.completed") {
        const artifact = event.finalArtifact;
        const resolvedHtml = artifactToHtml(artifact);
        const messages = [...next.messages];
        if (artifact?.kind === "evidence_only" && artifact.answer) {
          messages.push({
            id: `${threadId}-${Date.now()}`,
            role: "assistant",
            content: artifact.answer,
            format: "markdown",
            timestamp: Date.now(),
            agentName: "GraphRAG",
          });
        } else if (artifact?.kind === "content") {
          messages.push(statusMessage("Vangogh artifact rendered in the preview pane.", "Vangogh"));
        } else if (artifact?.kind === "error" && artifact.error_message) {
          messages.push(statusMessage(`Workflow error: ${artifact.error_message}`));
        }
        next = {
          ...next,
          status: "complete",
          finalArtifact: artifact,
          resolvedHtml,
          governanceReport: artifact?.governance_report ?? next.governanceReport,
          schemaDraft: artifact?.schema_data ?? next.schemaDraft,
          messages,
          timeline: [
            ...next.timeline,
            timelineEntry(event.kind === "run.regeneration.completed" ? "Artifact regenerated" : "Workflow complete", "done"),
          ],
          updatedAt: new Date().toISOString(),
        };
      }

      if (event.kind === "run.regeneration.started") {
        next = {
          ...next,
          timeline: [...next.timeline, timelineEntry("Regenerating with edited schema...", "active")],
          updatedAt: new Date().toISOString(),
        };
      }

      if (event.kind === "run.failed") {
        next = {
          ...next,
          status: "error",
          lastError: event.message,
          messages: [...next.messages, statusMessage(event.message)],
          timeline: [...next.timeline, timelineEntry(`Error: ${event.message}`, "failed")],
          updatedAt: new Date().toISOString(),
        };
      }

      if (event.kind === "run.rehydrated") {
        next = {
          ...next,
          status: event.status,
          currentNode: event.currentNode,
          finalArtifact: event.finalArtifact,
          resolvedHtml: artifactToHtml(event.finalArtifact),
          governanceReport: event.finalArtifact?.governance_report ?? next.governanceReport,
          schemaDraft: event.finalArtifact?.schema_data ?? next.schemaDraft,
          updatedAt: event.updatedAt,
          hitl: event.hitlRequired
            ? {
                threadId,
                agentNode: next.hitl?.agentNode ?? "content_node",
                questions: event.hitlQuestions,
                draftAnswers: next.hitl?.draftAnswers ?? {},
              }
            : null,
        };
      }

      return {
        ...state,
        workspace: {
          ...state.workspace,
          activeThreadId: threadId,
          activeSessionId: next.sessionId || state.workspace.activeSessionId,
        },
        runsById: { ...state.runsById, [threadId]: next },
        history: { recentThreadIds: mergeRecent(state.history.recentThreadIds, threadId) },
        connection: {
          ...state.connection,
          status: event.kind === "run.failed" ? "error" : event.kind === "run.completed" || event.kind === "run.regeneration.completed" ? "ready" : state.connection.status,
        },
      };
    }
    default:
      return state;
  }
}

function reducer(state: OrchestrationState, action: Action): OrchestrationState {
  switch (action.type) {
    case "toggleSidebar":
      return { ...state, ui: { ...state.ui, sidebarCollapsed: !state.ui.sidebarCollapsed } };
    case "setActivePane":
      return { ...state, ui: { ...state.ui, activePane: action.pane } };
    case "openSchemaDrawer":
      return { ...state, ui: { ...state.ui, schemaDrawerOpen: action.open } };
    case "openGovernanceDrawer":
      return { ...state, ui: { ...state.ui, governanceDrawerOpen: action.open } };
    case "setPendingPrompt":
      return {
        ...state,
        workspace: { ...state.workspace, workflowMode: action.workflowMode },
        connection: { ...state.connection, pendingPrompt: action.prompt },
      };
    case "ingestEvent":
      return reduceEvent(state, action.event);
    case "selectRun":
      return { ...state, workspace: { ...state.workspace, activeThreadId: action.threadId } };
    case "setHitlDraft": {
      const run = state.runsById[action.threadId];
      if (!run?.hitl) return state;
      return {
        ...state,
        runsById: {
          ...state.runsById,
          [action.threadId]: {
            ...run,
            hitl: {
              ...run.hitl,
              draftAnswers: { ...run.hitl.draftAnswers, [action.questionKey]: action.value },
            },
          },
        },
      };
    }
    case "appendSystemMessage": {
      const run = state.runsById[action.threadId];
      if (!run) return state;
      return {
        ...state,
        runsById: {
          ...state.runsById,
          [action.threadId]: {
            ...run,
            messages: [...run.messages, statusMessage(action.content)],
          },
        },
      };
    }
    case "hydrateWorkflows":
      return {
        ...state,
        history: {
          recentThreadIds: Array.from(new Set([...action.threadIds, ...state.history.recentThreadIds])).slice(0, 24),
        },
      };
    case "uploadStarted":
      return { ...state, uploads: { items: [action.item, ...state.uploads.items] } };
    case "uploadFinished":
      return {
        ...state,
        uploads: {
          items: state.uploads.items.map((item) => (item.id === action.id ? { ...item, status: action.status, message: action.message } : item)),
        },
      };
    case "setConnection":
      return { ...state, connection: { ...state.connection, status: action.status } };
    default:
      return state;
  }
}

function restoreState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return initialState;
    const parsed = JSON.parse(raw) as Partial<OrchestrationState>;
    return {
      ...initialState,
      workspace: { ...initialState.workspace, ...parsed.workspace },
      history: { ...initialState.history, ...parsed.history },
      ui: { ...initialState.ui, ...parsed.ui },
      runsById: parsed.runsById ?? {},
    };
  } catch {
    return initialState;
  }
}

const OrchestrationContext = createContext<{
  state: OrchestrationState;
  dispatch: React.Dispatch<Action>;
} | null>(null);

export function OrchestrationProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState, restoreState);

  useEffect(() => {
    const payload = {
      workspace: {
        tenantId: state.workspace.tenantId,
        activeThreadId: state.workspace.activeThreadId,
        activeSessionId: state.workspace.activeSessionId,
        workflowMode: state.workspace.workflowMode,
      },
      history: state.history,
      ui: state.ui,
      runsById: Object.fromEntries(
        Object.entries(state.runsById).map(([threadId, run]) => [
          threadId,
          {
            threadId: run.threadId,
            sessionId: run.sessionId,
            workflowMode: run.workflowMode,
            executionMode: run.executionMode,
            status: run.status,
            currentNode: run.currentNode,
            userQuery: run.userQuery,
            updatedAt: run.updatedAt,
            finalArtifact: run.finalArtifact,
            resolvedHtml: run.resolvedHtml,
            governanceReport: run.governanceReport,
            schemaDraft: run.schemaDraft,
            hitl: run.hitl,
            lastError: run.lastError,
            messages: run.messages,
            timeline: run.timeline,
          },
        ]),
      ),
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  }, [state]);

  const value = useMemo(() => ({ state, dispatch }), [state]);
  return <OrchestrationContext.Provider value={value}>{children}</OrchestrationContext.Provider>;
}

export function useOrchestration() {
  const context = useContext(OrchestrationContext);
  if (!context) {
    throw new Error("useOrchestration must be used inside OrchestrationProvider");
  }
  return context;
}
