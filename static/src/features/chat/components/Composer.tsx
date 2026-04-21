import { useState } from "react";

export function Composer({
  disabled,
  onSubmit,
}: {
  disabled: boolean;
  onSubmit: (prompt: string, workflowMode: string) => Promise<void>;
}) {
  const [prompt, setPrompt] = useState("");
  const [workflowMode, setWorkflowMode] = useState("standard");

  async function handleSubmit() {
    const trimmed = prompt.trim();
    if (!trimmed || disabled) return;
    await onSubmit(trimmed, workflowMode);
    setPrompt("");
  }

  return (
    <div className="composer">
      <div className="composer__controls">
        <select value={workflowMode} onChange={(event) => setWorkflowMode(event.target.value)}>
          <option value="standard">Standard</option>
          <option value="creative">Creative</option>
          <option value="deep_research">Deep Research</option>
        </select>
      </div>
      <textarea
        value={prompt}
        onChange={(event) => setPrompt(event.target.value)}
        placeholder="Describe the workflow you want the agents to run..."
        rows={4}
      />
      <div className="composer__actions">
        <button type="button" onClick={handleSubmit} disabled={disabled || !prompt.trim()}>
          {disabled ? "Streaming..." : "Run workflow"}
        </button>
      </div>
    </div>
  );
}
