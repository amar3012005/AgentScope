import { CONFIG } from "../../config";
import { apiGet, apiPost, buildApiUrl, createApiHeaders, fetchWithRetry } from "../../api/client";
import { streamSSE } from "../../api/sse";
import type {
  OrchestratorStreamHandlers,
  RegenerateWorkflowRequest,
  ResumeWorkflowRequest,
  SaveChatSnapshotRequest,
  SaveChatSnapshotResponse,
  SubmitWorkflowRequest,
  UploadDocumentRequest,
  UploadDocumentResponse,
  WorkflowListResponse,
  WorkflowStatusResponse,
} from "./types";

export function submitWorkflow(
  request: SubmitWorkflowRequest,
  handlers: OrchestratorStreamHandlers
): Promise<void> {
  return streamSSE(
    "/api/v4/orchestrator/submit",
    {
      user_query: request.user_query,
      workflow_mode: request.workflow_mode ?? "standard",
      collection_name: request.collection_name,
      session_id: request.session_id,
      use_template_engine: request.use_template_engine,
    },
    handlers.onEvent,
    () => handlers.onDone?.(),
    (error) => handlers.onError?.(error)
  );
}

export function resumeWorkflow(
  request: ResumeWorkflowRequest,
  handlers: OrchestratorStreamHandlers
): Promise<void> {
  return streamSSE(
    "/api/v4/orchestrator/resume",
    {
      thread_id: request.thread_id,
      agent_node: request.agent_node,
      answers: request.answers,
    },
    handlers.onEvent,
    () => handlers.onDone?.(),
    (error) => handlers.onError?.(error)
  );
}

export function regenerateWorkflow(
  request: RegenerateWorkflowRequest,
  handlers: OrchestratorStreamHandlers
): Promise<void> {
  return streamSSE(
    "/api/v4/orchestrator/regenerate",
    {
      thread_id: request.thread_id,
      patched_schema: request.patched_schema,
      workflow_mode: request.workflow_mode ?? "standard",
    },
    handlers.onEvent,
    () => handlers.onDone?.(),
    (error) => handlers.onError?.(error)
  );
}

export async function getWorkflowStatus(
  threadId: string
): Promise<WorkflowStatusResponse> {
  const response = await apiGet(`/api/v4/orchestrator/status/${threadId}`);
  return (await response.json()) as WorkflowStatusResponse;
}

export async function listWorkflows(): Promise<WorkflowListResponse> {
  const response = await apiGet("/api/v4/orchestrator/workflows");
  return (await response.json()) as WorkflowListResponse;
}

export async function uploadDocument(
  request: UploadDocumentRequest
): Promise<UploadDocumentResponse> {
  const formData = new FormData();
  formData.append("file", request.file);
  formData.append("tenant_id", CONFIG.TENANT_ID);

  if (request.metadata !== undefined) {
    formData.append(
      "metadata",
      typeof request.metadata === "string"
        ? request.metadata
        : JSON.stringify(request.metadata)
    );
  }

  const response = await fetchWithRetry(buildApiUrl("/upload"), {
    method: "POST",
    headers: createApiHeaders(),
    body: formData,
  });

  if (!response.ok) {
    throw new Error(`POST /upload failed: ${response.status} ${response.statusText}`);
  }

  return (await response.json()) as UploadDocumentResponse;
}

export async function saveChatSnapshot(
  request: SaveChatSnapshotRequest
): Promise<SaveChatSnapshotResponse> {
  const payload = request as unknown as Record<string, unknown>;
  const response = await apiPost("/api/v4/orchestrator/chats/save", payload);
  return (await response.json()) as SaveChatSnapshotResponse;
}
