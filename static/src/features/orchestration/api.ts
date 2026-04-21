import { CONFIG } from "../../config";
import { apiGet, buildApiUrl, createApiHeaders, fetchWithRetry } from "../../api/client";
import { streamSSE } from "../../api/sse";
import type { FinalArtifact } from "../../types";
import type { RawSseEvent, RegenerateRequest, ResumeRequest, SubmitRequest, UploadResponse, WorkflowsResponse, WorkflowStatusResponse } from "./contracts";

function headers(extra?: Record<string, string>) {
  return createApiHeaders({
    Accept: "application/json",
    ...(extra ?? {}),
  });
}

function toUrl(path: string) {
  return buildApiUrl(path);
}

export async function streamJsonEvents(
  path: string,
  body: Record<string, unknown>,
  onEvent: (event: RawSseEvent) => void,
) {
  let streamError: Error | null = null;
  await streamSSE<RawSseEvent>(
    path,
    body,
    onEvent,
    () => {
      // no-op
    },
    (error) => {
      streamError = error;
    }
  );
  if (streamError) {
    throw streamError;
  }
}

export function submitRun(payload: Omit<SubmitRequest, "tenant_id">, onEvent: (event: RawSseEvent) => void) {
  return streamJsonEvents("/api/v4/orchestrator/submit", payload as Record<string, unknown>, onEvent);
}

export function resumeRun(payload: ResumeRequest, onEvent: (event: RawSseEvent) => void) {
  return streamJsonEvents(
    "/api/v4/orchestrator/resume",
    payload as unknown as Record<string, unknown>,
    onEvent
  );
}

export function regenerateRun(payload: RegenerateRequest, onEvent: (event: RawSseEvent) => void) {
  return streamJsonEvents(
    "/api/v4/orchestrator/regenerate",
    payload as unknown as Record<string, unknown>,
    onEvent
  );
}

export async function getRunStatus(threadId: string) {
  const response = await apiGet(`/api/v4/orchestrator/status/${threadId}`);
  return (await response.json()) as WorkflowStatusResponse;
}

export async function listWorkflows() {
  const response = await apiGet("/api/v4/orchestrator/workflows");
  return (await response.json()) as WorkflowsResponse;
}

export async function uploadKnowledgeFile(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("tenant_id", CONFIG.TENANT_ID);

  const requestHeaders: Record<string, string> = {};
  if (CONFIG.API_KEY) {
    requestHeaders["X-API-Key"] = CONFIG.API_KEY;
  }

  const response = await fetchWithRetry(toUrl("/upload"), {
    method: "POST",
    headers: requestHeaders,
    body: formData,
  });

  if (!response.ok) {
    throw new Error(`upload failed: ${response.status} ${response.statusText}`);
  }
  return (await response.json()) as UploadResponse;
}

export function artifactToHtml(artifact: FinalArtifact | null) {
  if (!artifact) return "";
  return artifact.governance_report?.approved_output ?? artifact.html_artifact ?? "";
}
