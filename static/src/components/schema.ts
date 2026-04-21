import { createElement, escapeHtml } from "../utils/dom";
import { state } from "../state";
import { streamSSE } from "../api/sse";
import type { ContentSchema, SSEEvent } from "../types";

let panelEl: HTMLElement | null = null;
let fieldsContainer: HTMLElement | null = null;
let currentSchema: ContentSchema | null = null;
let handleEventRef: ((event: SSEEvent) => void) | null = null;

/** Must be called from main.ts to wire the shared event handler */
export function setEventHandler(handler: (event: SSEEvent) => void): void {
  handleEventRef = handler;
}

function createTagField(
  label: string,
  values: string[],
  onChange: (newValues: string[]) => void
): HTMLElement {
  const field = createElement("div", { class: "schema-field" });
  const labelEl = createElement("label", { class: "schema-field-label" }, [label]);
  field.appendChild(labelEl);

  const tagsContainer = createElement("div", { class: "schema-tags" });

  function renderTags(): void {
    tagsContainer.innerHTML = "";
    for (let i = 0; i < values.length; i++) {
      const tag = createElement("span", { class: "schema-tag" });
      tag.appendChild(document.createTextNode(escapeHtml(values[i])));

      const removeBtn = createElement("button", {
        class: "schema-tag-remove",
        type: "button",
        "aria-label": `Remove ${values[i]}`,
      }, ["\u00D7"]);

      removeBtn.addEventListener("click", () => {
        values.splice(i, 1);
        onChange([...values]);
        renderTags();
      });

      tag.appendChild(removeBtn);
      tagsContainer.appendChild(tag);
    }

    const addBtn = createElement("button", {
      class: "schema-tag-add",
      type: "button",
    }, ["+ Add"]);

    addBtn.addEventListener("click", () => {
      const value = prompt("Enter new value:");
      if (value && value.trim()) {
        values.push(value.trim());
        onChange([...values]);
        renderTags();
      }
    });

    tagsContainer.appendChild(addBtn);
  }

  renderTags();
  field.appendChild(tagsContainer);
  return field;
}

function createTextareaField(
  label: string,
  value: string,
  onChange: (newValue: string) => void
): HTMLElement {
  const field = createElement("div", { class: "schema-field" });
  const labelEl = createElement("label", { class: "schema-field-label" }, [label]);
  const input = createElement("textarea", {
    class: "schema-field-input",
    rows: "2",
  }) as HTMLTextAreaElement;
  input.value = value;

  input.addEventListener("input", () => {
    onChange(input.value);
  });

  field.appendChild(labelEl);
  field.appendChild(input);
  return field;
}

function renderFields(schema: ContentSchema): void {
  if (!fieldsContainer) return;
  fieldsContainer.innerHTML = "";

  fieldsContainer.appendChild(
    createTextareaField("Vision Statement", schema.vision_statement, (v) => {
      schema.vision_statement = v;
    })
  );

  fieldsContainer.appendChild(
    createTextareaField("Target Audience", schema.target_audience, (v) => {
      schema.target_audience = v;
    })
  );

  fieldsContainer.appendChild(
    createTagField("KPIs", [...schema.kpis], (v) => {
      schema.kpis = v;
    })
  );

  fieldsContainer.appendChild(
    createTagField("Strategic Pillars", [...schema.strategic_pillars], (v) => {
      schema.strategic_pillars = v;
    })
  );

  fieldsContainer.appendChild(
    createTextareaField("Timeline", schema.timeline, (v) => {
      schema.timeline = v;
    })
  );

  // Regenerate button
  const regenBtn = createElement("button", {
    class: "schema-regenerate",
    type: "button",
  }, ["\u21BB Regenerate with edits"]);

  regenBtn.addEventListener("click", () => {
    if (!currentSchema || !handleEventRef) return;

    regenBtn.disabled = true;
    regenBtn.textContent = "Regenerating...";

    const patchedSchema = {
      vision_statement: currentSchema.vision_statement,
      target_audience: currentSchema.target_audience,
      kpis: currentSchema.kpis,
      strategic_pillars: currentSchema.strategic_pillars,
      timeline: currentSchema.timeline,
    };

    streamSSE(
      "/api/v4/orchestrator/regenerate",
      {
        thread_id: state.threadId,
        patched_schema: patchedSchema,
        workflow_mode: "standard",
      },
      handleEventRef,
      () => {
        regenBtn.disabled = false;
        regenBtn.textContent = "\u21BB Regenerate with edits";
      },
      (err: Error) => {
        regenBtn.disabled = false;
        regenBtn.textContent = "\u21BB Regenerate with edits";
        // Log error for debugging
        if (typeof console !== "undefined") {
          console.error("Regeneration failed:", err.message);
        }
      }
    );
  });

  fieldsContainer.appendChild(regenBtn);
}

export function mountSchema(container: HTMLElement): void {
  panelEl = createElement("div", {
    class: "schema-panel",
    style: "display:none",
  });

  const header = createElement("div", { class: "schema-header" });
  const title = createElement("div", { class: "schema-title" }, ["CONTENT SCHEMA"]);
  const closeBtn = createElement("button", {
    class: "schema-close",
    type: "button",
    "aria-label": "Close schema panel",
  }, ["\u00D7"]);

  closeBtn.addEventListener("click", hide);

  header.appendChild(title);
  header.appendChild(closeBtn);

  fieldsContainer = createElement("div", { class: "schema-fields" });

  panelEl.appendChild(header);
  panelEl.appendChild(fieldsContainer);
  container.appendChild(panelEl);
}

export function show(schema: ContentSchema): void {
  currentSchema = { ...schema, kpis: [...schema.kpis], strategic_pillars: [...schema.strategic_pillars] };
  state.schema = currentSchema;
  state.schemaVisible = true;

  if (panelEl) {
    panelEl.style.display = "block";
    renderFields(currentSchema);
  }
}

export function hide(): void {
  state.schemaVisible = false;
  if (panelEl) {
    panelEl.style.display = "none";
  }
}
