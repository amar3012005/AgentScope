import {
  buildApiUrl,
  createApiHeaders,
  fetchWithRetry,
  isRetryableNetworkError,
  withTenantId,
} from "./client";
import type { SSEEvent } from "../types";

const SSE_RECONNECT_ATTEMPTS = 1;
const SSE_RECONNECT_DELAY_MS = 500;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function consumeSSEStream<TEvent extends Record<string, unknown>>(
  response: Response,
  onEvent: (event: TEvent) => void
): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("Response body is not readable");
  }

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      const trimmed = line.trim();

      if (!trimmed || trimmed.startsWith(":")) {
        continue;
      }

      if (trimmed === "data: [DONE]") {
        return;
      }

      if (trimmed.startsWith("data: ")) {
        const json = trimmed.slice(6);
        try {
          const event = JSON.parse(json) as TEvent;
          onEvent(event);
        } catch {
          // Malformed JSON line — skip
        }
      }
    }
  }

  if (buffer.trim()) {
    const trimmed = buffer.trim();
    if (trimmed === "data: [DONE]") {
      return;
    }
    if (trimmed.startsWith("data: ")) {
      try {
        const event = JSON.parse(trimmed.slice(6)) as TEvent;
        onEvent(event);
      } catch {
        // Malformed final line — skip
      }
    }
  }
}

export async function streamSSE<TEvent extends Record<string, unknown> = SSEEvent>(
  path: string,
  body: Record<string, unknown>,
  onEvent: (event: TEvent) => void,
  onDone: () => void,
  onError: (err: Error) => void,
  reconnectAttempts = SSE_RECONNECT_ATTEMPTS
): Promise<void> {
  const headers = createApiHeaders({
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  });
  const payload = withTenantId(body);

  let reconnectAttempt = 0;
  while (true) {
    try {
      const response = await fetchWithRetry(
        buildApiUrl(path),
        {
          method: "POST",
          headers,
          body: JSON.stringify(payload),
        }
      );

      if (!response.ok) {
        onError(new Error(`SSE request failed: ${response.status} ${response.statusText}`));
        return;
      }

      await consumeSSEStream(response, onEvent);
      onDone();
      return;
    } catch (error) {
      const normalized = error instanceof Error ? error : new Error(String(error));
      if (isRetryableNetworkError(normalized) && reconnectAttempt < reconnectAttempts) {
        reconnectAttempt += 1;
        await sleep(SSE_RECONNECT_DELAY_MS * reconnectAttempt);
        continue;
      }
      onError(normalized);
      return;
    }
  }
}
