import { useState } from "react";
import type { HitlPrompt } from "../types";

export function HitlModal({
  prompt,
  onChange,
  onSubmit,
}: {
  prompt: HitlPrompt | null;
  onChange: (key: string, value: string) => void;
  onSubmit: () => Promise<void>;
}) {
  const [submitting, setSubmitting] = useState(false);

  if (!prompt) return null;

  return (
    <div className="modal-backdrop">
      <div className="modal-panel">
        <div className="modal-panel__eyebrow">Human in the loop</div>
        <h3>Answer the clarification prompts to continue the workflow.</h3>
        <div className="modal-panel__grid">
          {prompt.questions.map((question, index) => {
            const key = `q${index + 1}`;
            return (
              <label key={key} className="modal-panel__question">
                <span>{question}</span>
                <textarea value={prompt.draftAnswers[key] ?? ""} onChange={(event) => onChange(key, event.target.value)} rows={4} />
              </label>
            );
          })}
        </div>
        <button
          type="button"
          disabled={submitting}
          onClick={async () => {
            setSubmitting(true);
            try {
              await onSubmit();
            } finally {
              setSubmitting(false);
            }
          }}
        >
          {submitting ? "Resuming..." : "Resume workflow"}
        </button>
      </div>
    </div>
  );
}
