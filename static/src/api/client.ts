import { CONFIG } from "../config";

const NETWORK_RETRY_ATTEMPTS = 1;
const NETWORK_RETRY_BASE_DELAY_MS = 300;

export function createApiHeaders(
  extra: Record<string, string> = {}
): Record<string, string> {
  const h: Record<string, string> = { ...extra };
  if (CONFIG.API_KEY) {
    h["X-API-Key"] = CONFIG.API_KEY;
  }
  return h;
}

export function buildApiUrl(path: string): string {
  return `${CONFIG.API_BASE}${path}`;
}

export function withTenantId(
  payload: Record<string, unknown>
): Record<string, unknown> & { tenant_id: string } {
  return { ...payload, tenant_id: CONFIG.TENANT_ID };
}

export function isRetryableNetworkError(error: unknown): boolean {
  if (!(error instanceof Error)) {
    return false;
  }
  if (error.name === "AbortError") {
    return false;
  }
  if (error instanceof TypeError) {
    return true;
  }
  const message = error.message.toLowerCase();
  return (
    message.includes("network") ||
    message.includes("failed to fetch") ||
    message.includes("load failed")
  );
}

function retryDelay(attempt: number): number {
  return NETWORK_RETRY_BASE_DELAY_MS * attempt;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

export async function fetchWithRetry(
  url: string,
  init: RequestInit,
  retryAttempts = NETWORK_RETRY_ATTEMPTS
): Promise<Response> {
  let attempt = 0;

  while (true) {
    try {
      return await fetch(url, init);
    } catch (error) {
      if (!isRetryableNetworkError(error) || attempt >= retryAttempts) {
        throw error;
      }
      attempt += 1;
      await sleep(retryDelay(attempt));
    }
  }
}

export async function apiPost(
  path: string,
  body: Record<string, unknown>
): Promise<Response> {
  const payload = withTenantId(body);
  const response = await fetchWithRetry(buildApiUrl(path), {
    method: "POST",
    headers: createApiHeaders({
      "Content-Type": "application/json",
      Accept: "application/json",
    }),
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`POST ${path} failed: ${response.status} ${response.statusText}`);
  }
  return response;
}

export async function apiGet(path: string): Promise<Response> {
  const hasTenant = /[?&]tenant_id=/.test(path);
  const separator = path.includes("?") ? "&" : "?";
  const tenantPath = hasTenant
    ? path
    : `${path}${separator}tenant_id=${encodeURIComponent(CONFIG.TENANT_ID)}`;
  const response = await fetchWithRetry(buildApiUrl(tenantPath), {
    method: "GET",
    headers: createApiHeaders({
      Accept: "application/json",
    }),
  });
  if (!response.ok) {
    throw new Error(`GET ${path} failed: ${response.status} ${response.statusText}`);
  }
  return response;
}
