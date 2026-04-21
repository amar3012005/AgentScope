export const CONFIG = {
  API_BASE: import.meta.env.VITE_API_BASE || "",
  TENANT_ID: import.meta.env.VITE_TENANT_ID || "default",
  API_KEY: import.meta.env.VITE_API_KEY || "",
} as const;

export const CONTENT_KEYWORDS = [
  "pitch deck",
  "poster",
  "generate",
  "create",
  "design",
  "presentation",
  "slide",
  "landing page",
  "website",
  "dashboard",
  "report",
  "infographic",
  "brochure",
] as const;

export function isContentQuery(msg: string): boolean {
  const lower = msg.toLowerCase();
  return CONTENT_KEYWORDS.some((kw) => lower.includes(kw));
}
