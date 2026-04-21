import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useReducer,
  type ReactNode,
} from "react";
import { CONFIG } from "../../config";
import { createId } from "./timeline";
import {
  getWorkflowStatus,
  listWorkflows,
  regenerateWorkflow,
  resumeWorkflow,
  saveChatSnapshot as saveChatSnapshotRequest,
  submitWorkflow,
  uploadDocument,
} from "./client";
import {
  createInitialState,
  orchestratorReducer,
  type OrchestratorAction,
} from "./reducer";
import type {
  OrchestratorHydration,
  OrchestratorState,
  OrchestratorStreamHandlers,
  RegenerateWorkflowRequest,
  ResumeWorkflowRequest,
  SubmitWorkflowRequest,
  UploadState,
  WorkflowStatusResponse,
} from "./types";

interface OrchestratorStoreValue {
  state: OrchestratorState;
  dispatch: (action: OrchestratorAction) => void;
  hydrate: (payload: OrchestratorHydration) => void;
  sendMessage: (text: string) => Promise<void>;
  resume: (request: ResumeWorkflowRequest) => Promise<void>;
  regenerate: (request: RegenerateWorkflowRequest) => Promise<void>;
  refreshStatus: (threadId?: string) => Promise<WorkflowStatusResponse | null>;
  refreshWorkflows: () => Promise<void>;
  uploadFiles: (files: File[], metadata?: Record<string, unknown>) => Promise<void>;
  addUserMessage: (text: string) => void;
  addSystemMessage: (text: string) => void;
  openArtifact: (html: string, title?: string, source?: OrchestratorState["artifact"]["source"]) => void;
  saveChatSnapshot: () => Promise<void>;
  startNewChat: () => Promise<void>;
  clearRun: () => void;
}

const STORAGE_KEY = "blaiq_orchestrator_store";
const ACCEPTED_UPLOAD_EXTENSIONS = [".pdf", ".docx", ".txt", ".md"];
const MAX_UPLOAD_SIZE = 50 * 1024 * 1024;
const OrchestratorContext = createContext<OrchestratorStoreValue | null>(null);

function readHydration(): OrchestratorHydration {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return {};
    }
    return JSON.parse(raw) as OrchestratorHydration;
  } catch {
    return {};
  }
}

function persistHydration(state: OrchestratorState): void {
  try {
    const payload: OrchestratorHydration = {
      threadId: state.threadId,
      sessionId: state.sessionId,
      runId: state.runId,
      messages: state.messages.slice(-200),
      uploads: state.uploads.slice(-50),
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // Ignore storage failures.
  }
}

function createEventHandlers(dispatch: (action: OrchestratorAction) => void): OrchestratorStreamHandlers {
  return {
    onEvent: (event) => {
      dispatch({ type: "apply-event", event });
    },
  };
}

function shouldUseTemplateEngine(query: string): boolean {
  const normalized = query.trim().toLowerCase();
  if (!normalized) {
    return false;
  }
  return [
    "pitch deck",
    "pitchdeck",
    "poster",
    "flyer",
    "brochure",
    "one-pager",
    "one pager",
    "landing page",
    "presentation",
    "slide deck",
    "slides",
    "visual",
    "banner",
    "infographic",
    "mockup",
    "design",
    "create",
    "generate",
  ].some((keyword) => normalized.includes(keyword));
}

export function OrchestratorStoreProvider({
  children,
  tenantId = CONFIG.TENANT_ID,
}: {
  children: ReactNode;
  tenantId?: string;
}): JSX.Element {
  const [state, dispatch] = useReducer(
    orchestratorReducer,
    createInitialState(tenantId)
  );
  const stateRef = useRef(state);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    dispatch({ type: "hydrate", payload: readHydration() });
  }, []);

  useEffect(() => {
    persistHydration(state);
  }, [state]);

  const hydrate = useCallback((payload: OrchestratorHydration): void => {
    dispatch({ type: "hydrate", payload });
  }, []);

  const addUserMessage = useCallback((text: string): void => {
    dispatch({
      type: "add-message",
      message: {
        id: createId(),
        role: "user",
        text,
        createdAt: Date.now(),
      },
    });
  }, []);

  const addSystemMessage = useCallback((text: string): void => {
    dispatch({
      type: "add-message",
      message: {
        id: createId(),
        role: "system",
        text,
        agentName: "Orchestrator",
        createdAt: Date.now(),
      },
    });
  }, []);

  const openArtifact = useCallback((
    html: string,
    title = "Artifact preview",
    source: OrchestratorState["artifact"]["source"] = "complete"
  ): void => {
    dispatch({
      type: "set-artifact",
      payload: {
        html,
        title,
        visible: true,
        source,
        loading: false,
        loadingLabel: "",
      },
    });
  }, []);

  const submit = useCallback(async (request: SubmitWorkflowRequest): Promise<void> => {
    dispatch({ type: "set-processing", key: "isSubmitting", value: true });
    dispatch({ type: "set-last-error", message: "" });
    addUserMessage(request.user_query);
    dispatch({
      type: "append-timeline",
      entry: {
        id: createId(),
        label: "Submitting workflow",
        status: "active",
        timestamp: Date.now(),
      },
    });

    await submitWorkflow(request, {
      ...createEventHandlers(dispatch),
      onDone: () => {
        dispatch({ type: "set-processing", key: "isSubmitting", value: false });
      },
      onError: (error) => {
        dispatch({ type: "set-processing", key: "isSubmitting", value: false });
        addSystemMessage(`Connection error: ${error.message}`);
        dispatch({ type: "set-last-error", message: error.message });
      },
    });
  }, [addUserMessage]);

  const sendMessage = useCallback(async (text: string): Promise<void> => {
    await submit({
      user_query: text,
      workflow_mode: stateRef.current.workflowMode,
      session_id: stateRef.current.sessionId,
      use_template_engine: shouldUseTemplateEngine(text),
    });
  }, [submit]);

  const resume = useCallback(async (request: ResumeWorkflowRequest): Promise<void> => {
    dispatch({ type: "set-processing", key: "isResuming", value: true });
    await resumeWorkflow(request, {
      ...createEventHandlers(dispatch),
      onDone: () => {
        dispatch({ type: "set-processing", key: "isResuming", value: false });
      },
      onError: (error) => {
        dispatch({ type: "set-processing", key: "isResuming", value: false });
        addSystemMessage(`Resume failed: ${error.message}`);
        dispatch({ type: "set-last-error", message: error.message });
      },
    });
  }, []);

  const regenerate = useCallback(async (request: RegenerateWorkflowRequest): Promise<void> => {
    dispatch({ type: "set-processing", key: "isRegenerating", value: true });
    await regenerateWorkflow(request, {
      ...createEventHandlers(dispatch),
      onDone: () => {
        dispatch({ type: "set-processing", key: "isRegenerating", value: false });
      },
      onError: (error) => {
        dispatch({ type: "set-processing", key: "isRegenerating", value: false });
        addSystemMessage(`Regeneration failed: ${error.message}`);
        dispatch({ type: "set-last-error", message: error.message });
      },
    });
  }, []);

  const refreshStatus = useCallback(async (
    threadId = stateRef.current.threadId
  ): Promise<WorkflowStatusResponse | null> => {
    if (!threadId) {
      return null;
    }
    const status = await getWorkflowStatus(threadId);
    dispatch({ type: "set-status", payload: status });
    return status;
  }, []);

  const refreshWorkflows = useCallback(async (): Promise<void> => {
    const response = await listWorkflows();
    dispatch({ type: "set-workflows", workflows: response.workflows });
  }, []);

  const uploadFiles = useCallback(async (
    files: File[],
    metadata?: Record<string, unknown>
  ): Promise<void> => {
    for (const file of files) {
      const uploadId = createId();

      const lowerName = file.name.toLowerCase();
      const isAccepted = ACCEPTED_UPLOAD_EXTENSIONS.some((ext) =>
        lowerName.endsWith(ext)
      );
      if (!isAccepted) {
        dispatch({
          type: "upsert-upload",
          upload: {
            id: uploadId,
            name: file.name,
            size: file.size,
            status: "error",
            message: "Unsupported file type",
          },
        });
        continue;
      }

      if (file.size > MAX_UPLOAD_SIZE) {
        dispatch({
          type: "upsert-upload",
          upload: {
            id: uploadId,
            name: file.name,
            size: file.size,
            status: "error",
            message: "File too large (max 50MB)",
          },
        });
        continue;
      }

      const optimistic: UploadState = {
        id: uploadId,
        name: file.name,
        size: file.size,
        status: "uploading",
      };
      dispatch({ type: "upsert-upload", upload: optimistic });

      try {
        const response = await uploadDocument({ file, metadata });
        dispatch({
          type: "update-upload",
          id: uploadId,
          patch: {
            status: response.status === "success" ? "success" : "error",
            message: response.status,
          },
        });
      } catch (error) {
        dispatch({
          type: "update-upload",
          id: uploadId,
          patch: {
            status: "error",
            message: error instanceof Error ? error.message : "Upload failed",
          },
        });
      }
    }
  }, []);

  const clearRun = useCallback((): void => {
    dispatch({ type: "clear-run" });
  }, []);

  const saveChatSnapshot = useCallback(async (): Promise<void> => {
    const current = stateRef.current;
    const hasContent =
      current.messages.length > 0 ||
      current.timeline.length > 0 ||
      Boolean(current.artifact.html) ||
      Boolean(current.threadId);

    if (!hasContent) {
      return;
    }

    try {
      await saveChatSnapshotRequest({
        thread_id: current.threadId || undefined,
        session_id: current.sessionId,
        run_id: current.runId || undefined,
        workflow_mode: current.workflowMode,
        messages: current.messages,
        timeline: current.timeline,
        artifact: current.artifact,
        governance: current.governance,
        schema: current.schema,
        status: current.status,
      });
    } catch (error) {
      addSystemMessage(
        `Chat export failed: ${error instanceof Error ? error.message : "Unknown error"}`
      );
    }
  }, [addSystemMessage]);

  const startNewChat = useCallback(async (): Promise<void> => {
    await saveChatSnapshot();
    dispatch({ type: "clear-run" });
    dispatch({ type: "set-session", sessionId: crypto.randomUUID() });
  }, [saveChatSnapshot]);

  const value: OrchestratorStoreValue = {
    state,
    dispatch,
    hydrate,
    sendMessage,
    resume,
    regenerate,
    refreshStatus,
    refreshWorkflows,
    uploadFiles,
    addUserMessage,
    addSystemMessage,
    openArtifact,
    saveChatSnapshot,
    startNewChat,
    clearRun,
  };

  return (
    <OrchestratorContext.Provider value={value}>
      {children}
    </OrchestratorContext.Provider>
  );
}

export function useOrchestratorStore(): OrchestratorStoreValue {
  const context = useContext(OrchestratorContext);
  if (!context) {
    throw new Error("useOrchestratorStore must be used within OrchestratorStoreProvider");
  }
  return context;
}
