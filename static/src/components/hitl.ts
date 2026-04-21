import { createElement, escapeHtml } from "../utils/dom";
import { trapFocus, onEscape } from "../utils/keyboard";
import { streamSSE } from "../api/sse";
import type { SSEEvent } from "../types";

let overlayEl: HTMLElement | null = null;
let panelEl: HTMLElement | null = null;
let cleanupTrap: (() => void) | null = null;
let cleanupEscape: (() => void) | null = null;
let handleEventRef: ((event: SSEEvent) => void) | null = null;

/** Must be called from main.ts to wire the shared event handler */
export function setEventHandler(handler: (event: SSEEvent) => void): void {
  handleEventRef = handler;
}

function getQuickChips(question: string): string[] {
  const lower = question.toLowerCase();

  if (lower.includes("audience") || lower.includes("target")) {
    return ["Enterprise CIOs", "Developers", "Startups"];
  }
  if (lower.includes("style") || lower.includes("design")) {
    return ["Modern minimal", "Bold cyber", "Dark premium"];
  }
  if (lower.includes("format") || lower.includes("output")) {
    return ["Pitch deck", "Dashboard", "Landing page"];
  }
  if (lower.includes("evidence") || lower.includes("data")) {
    return ["Use all available", "Key metrics only", "Custom"];
  }
  return ["Yes", "No", "Use defaults"];
}

export function mountHitl(): void {
  overlayEl = createElement("div", {
    class: "hitl-overlay",
    style: "display:none",
    role: "dialog",
    "aria-modal": "true",
    "aria-label": "Human-in-the-loop questions",
  });

  panelEl = createElement("div", { class: "hitl-panel" });
  overlayEl.appendChild(panelEl);
  document.body.appendChild(overlayEl);
}

export function show(
  questions: string[],
  threadId: string,
  agentNode: string
): void {
  if (!overlayEl || !panelEl || !handleEventRef) return;

  panelEl.innerHTML = "";

  // Header
  const header = createElement("div", { class: "hitl-header" });
  const title = createElement("h2", { class: "hitl-title" }, [
    "\u26A1 Vangogh needs a few details",
  ]);
  const subtitle = createElement("p", { class: "hitl-subtitle" }, [
    "Answer the questions below to continue generating your content.",
  ]);
  const badge = createElement("span", { class: "hitl-agent-badge" }, [
    `Node: ${escapeHtml(agentNode)}`,
  ]);
  header.appendChild(title);
  header.appendChild(subtitle);
  header.appendChild(badge);

  // Questions grid
  const grid = createElement("div", { class: "hitl-questions" });
  const textareas: HTMLTextAreaElement[] = [];

  for (let i = 0; i < questions.length; i++) {
    const card = createElement("div", { class: "hitl-question-card" });
    const numberLabel = createElement("div", { class: "hitl-question-number" }, [
      `Question ${i + 1}`,
    ]);
    const questionLabel = createElement("div", { class: "hitl-question-label" }, [
      escapeHtml(questions[i]),
    ]);
    const textarea = createElement("textarea", {
      class: "hitl-question-input",
      placeholder: "Type your answer...",
      "aria-label": `Answer for question ${i + 1}`,
    }) as HTMLTextAreaElement;

    textareas.push(textarea);

    // Quick chips
    const chipsContainer = createElement("div", { class: "hitl-quick-options" });
    const chips = getQuickChips(questions[i]);

    for (const chipText of chips) {
      const chip = createElement("button", {
        class: "hitl-quick-chip",
        type: "button",
      }, [chipText]);

      chip.addEventListener("click", () => {
        textarea.value = chipText;
        // Mark selected
        const siblings = chipsContainer.querySelectorAll(".hitl-quick-chip");
        siblings.forEach((s) => s.classList.remove("selected"));
        chip.classList.add("selected");
      });

      chipsContainer.appendChild(chip);
    }

    card.appendChild(numberLabel);
    card.appendChild(questionLabel);
    card.appendChild(textarea);
    card.appendChild(chipsContainer);
    grid.appendChild(card);
  }

  // Actions
  const actions = createElement("div", { class: "hitl-actions" });
  const cancelBtn = createElement("button", {
    class: "hitl-btn-cancel",
    type: "button",
  }, ["Cancel"]);
  const submitBtn = createElement("button", {
    class: "hitl-btn-submit",
    type: "button",
  }, ["Submit Answers"]);

  cancelBtn.addEventListener("click", hide);

  const eventHandler = handleEventRef;

  submitBtn.addEventListener("click", () => {
    const answers: Record<string, string> = {};
    for (let i = 0; i < questions.length; i++) {
      answers[`q${i + 1}`] = textareas[i].value || "Use defaults";
    }

    submitBtn.disabled = true;
    submitBtn.textContent = "Submitting...";

    streamSSE(
      "/api/v4/orchestrator/resume",
      {
        thread_id: threadId,
        agent_node: agentNode,
        answers,
      },
      eventHandler,
      () => {
        hide();
      },
      (err: Error) => {
        submitBtn.disabled = false;
        submitBtn.textContent = "Submit Answers";
        if (typeof console !== "undefined") {
          console.error("HITL resume failed:", err.message);
        }
      }
    );

    hide();
  });

  actions.appendChild(cancelBtn);
  actions.appendChild(submitBtn);

  panelEl.appendChild(header);
  panelEl.appendChild(grid);
  panelEl.appendChild(actions);

  overlayEl.style.display = "flex";

  // Focus trap and escape handler
  cleanupTrap = trapFocus(panelEl);
  cleanupEscape = onEscape(hide);

  // Focus first textarea
  if (textareas.length > 0) {
    textareas[0].focus();
  }
}

export function hide(): void {
  if (overlayEl) {
    overlayEl.style.display = "none";
  }
  if (cleanupTrap) {
    cleanupTrap();
    cleanupTrap = null;
  }
  if (cleanupEscape) {
    cleanupEscape();
    cleanupEscape = null;
  }
}
