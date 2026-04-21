const TENANT_ID = import.meta.env.VITE_TENANT_ID || 'default';
const API_KEY = import.meta.env.VITE_API_KEY || 'your_secure_api_key_here';

function createHeaders(extra = {}) {
  return API_KEY
    ? {
        ...extra,
        'X-API-Key': API_KEY,
      }
    : extra;
}

function withTenant(body) {
  return {
    tenant_id: TENANT_ID,
    ...body,
  };
}

async function consumeSSE(response, onEvent) {
  const reader = response.body?.getReader();
  if (!reader) throw new Error('Response body is not readable');

  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith(':')) continue;
      if (trimmed === 'data: [DONE]') return;
      if (!trimmed.startsWith('data: ')) continue;

      try {
        onEvent(JSON.parse(trimmed.slice(6)));
      } catch {
        // Ignore malformed lines.
      }
    }
  }
}

export async function streamWorkflow(path, body, onEvent) {
  const response = await fetch(path, {
    method: 'POST',
    headers: createHeaders({
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    }),
    body: JSON.stringify(withTenant(body)),
  });

  if (!response.ok) {
    throw new Error(`${path} failed: ${response.status} ${response.statusText}`);
  }

  await consumeSSE(response, onEvent);
}

export function submitWorkflow(payload, onEvent) {
  return streamWorkflow('/api/v4/orchestrator/submit', payload, onEvent);
}

export function resumeWorkflow(payload, onEvent) {
  return streamWorkflow('/api/v4/orchestrator/resume', payload, onEvent);
}

export async function getWorkflowStatus(threadId) {
  const response = await fetch(`/api/v4/orchestrator/status/${threadId}?tenant_id=${encodeURIComponent(TENANT_ID)}`, {
    headers: createHeaders({
      Accept: 'application/json',
    }),
  });
  if (!response.ok) {
    throw new Error(`Status request failed: ${response.status}`);
  }
  return response.json();
}
