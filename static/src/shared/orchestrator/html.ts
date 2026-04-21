export function normalizeArtifactHtml(rawHtml: string): string {
  let html = String(rawHtml || "");
  const fenceMatch = html.match(/```(?:html)?\s*([\s\S]*?)```/i);
  if (fenceMatch?.[1]) {
    html = fenceMatch[1].trim();
  }
  html = html.trim();

  if (!html) {
    return "<!doctype html><html><body style=\"margin:0;background:#f6f4f1;color:#111111;display:grid;place-items:center;font-family:system-ui;\"><h1 style=\"font-size:1rem;font-weight:600;\">No HTML artifact</h1></body></html>";
  }

  if (!/<html[\s>]|<body[\s>]|<!doctype/i.test(html)) {
    return `<!doctype html><html><body style="margin:0;background:#f6f4f1;color:#111111;padding:18px;font-family:ui-monospace,monospace;"><pre>${html
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")}</pre></body></html>`;
  }

  return html;
}
