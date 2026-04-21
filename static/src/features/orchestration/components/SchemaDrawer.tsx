import { useEffect, useState } from "react";
import type { ContentSchema } from "../../../types";

export function SchemaDrawer({
  schema,
  open,
  onClose,
  onRegenerate,
}: {
  schema: ContentSchema | null;
  open: boolean;
  onClose: () => void;
  onRegenerate: (schema: ContentSchema) => Promise<void>;
}) {
  const [draft, setDraft] = useState<ContentSchema>({
    strategic_pillars: [],
    kpis: [],
    target_audience: "",
    vision_statement: "",
    timeline: "",
  });

  useEffect(() => {
    if (schema) setDraft(schema);
  }, [schema]);

  if (!open) return null;

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(event) => event.stopPropagation()}>
        <div className="drawer__header">
          <span>Schema Editor</span>
          <button type="button" onClick={onClose}>
            Close
          </button>
        </div>
        <label>
          <span>Vision statement</span>
          <textarea value={draft.vision_statement} onChange={(event) => setDraft({ ...draft, vision_statement: event.target.value })} rows={3} />
        </label>
        <label>
          <span>Target audience</span>
          <textarea value={draft.target_audience} onChange={(event) => setDraft({ ...draft, target_audience: event.target.value })} rows={3} />
        </label>
        <label>
          <span>Timeline</span>
          <input value={draft.timeline} onChange={(event) => setDraft({ ...draft, timeline: event.target.value })} />
        </label>
        <label>
          <span>Strategic pillars</span>
          <textarea
            value={draft.strategic_pillars.join("\n")}
            onChange={(event) => setDraft({ ...draft, strategic_pillars: event.target.value.split("\n").map((item) => item.trim()).filter(Boolean) })}
            rows={5}
          />
        </label>
        <label>
          <span>KPIs</span>
          <textarea
            value={draft.kpis.join("\n")}
            onChange={(event) => setDraft({ ...draft, kpis: event.target.value.split("\n").map((item) => item.trim()).filter(Boolean) })}
            rows={5}
          />
        </label>
        <div className="drawer__actions">
          <button type="button" onClick={() => void onRegenerate(draft)}>
            Regenerate artifact
          </button>
        </div>
      </aside>
    </div>
  );
}
