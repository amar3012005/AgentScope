import React, { useState } from "react";

export default function UIShellApp({ page = "agents", title = "BLAIQ Workspace" }) {
  const [prompt, setPrompt] = useState("Generate a black and white poster");
  const [thinking, setThinking] = useState("");
  const [answer, setAnswer] = useState("Ready.");
  const [previewHtml, setPreviewHtml] = useState("");
  const [showPreview, setShowPreview] = useState(false);

  function run() {
    const text = prompt.trim();
    if (!text) return;
    setThinking("Analyzing intent and selecting the right subagents.");
    setAnswer("Thinking...");
    const wantsPoster = /poster|design|generate|content/i.test(text);
    if (wantsPoster) setShowPreview(true);

    setTimeout(() => {
      setThinking("");
      setAnswer(wantsPoster ? "Poster generated in Vangogh mode." : "Request processed.");
      if (wantsPoster) {
        setPreviewHtml(`<!doctype html><html><body style="margin:0;display:grid;place-items:center;min-height:100vh;background:#0b0b0b;color:#f5f5f5;font-family:system-ui"><h1>${text.replace(/[<>&]/g, "")}</h1></body></html>`);
      }
    }, 500);
  }

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <h1>{title}</h1>
      <div>Page: {page}</div>
      <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} />
      <button onClick={run}>Run</button>
      {thinking ? <pre>{`<thinking>${thinking}</thinking>`}</pre> : null}
      <pre style={{ fontWeight: 700 }}>{answer}</pre>
      {showPreview ? <iframe title="vangogh" srcDoc={previewHtml} style={{ width: "100%", minHeight: 380 }} /> : null}
    </div>
  );
}
