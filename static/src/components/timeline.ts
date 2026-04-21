import { createElement, escapeHtml } from "../utils/dom";
import { formatTime } from "../utils/format";
import type { TimelineStepStatus } from "../types";

interface Step {
  label: string;
  status: TimelineStepStatus;
  time: string;
  el: HTMLElement;
}

let panelEl: HTMLElement | null = null;
let stepsContainer: HTMLElement | null = null;
const steps: Step[] = [];

function createStepEl(label: string, status: TimelineStepStatus, time: string): HTMLElement {
  const step = createElement("div", {
    class: `timeline-step timeline-step--${status}`,
    "data-label": label,
  });

  const dot = createElement("div", { class: "timeline-step-dot" });
  const content = createElement("div", { class: "timeline-step-content" });
  const labelEl = createElement("div", { class: "timeline-step-label" }, [escapeHtml(label)]);
  const timeEl = createElement("div", { class: "timeline-step-time" }, [time]);

  content.appendChild(labelEl);
  content.appendChild(timeEl);
  step.appendChild(dot);
  step.appendChild(content);

  return step;
}

export function mountTimeline(container: HTMLElement): void {
  panelEl = createElement("div", { class: "timeline-panel", style: "display:none" });

  const header = createElement("div", { class: "timeline-header" }, ["EXECUTION PLAN"]);
  stepsContainer = createElement("div", { class: "timeline-steps" });

  panelEl.appendChild(header);
  panelEl.appendChild(stepsContainer);
  container.appendChild(panelEl);
}

export function show(): void {
  if (panelEl) {
    panelEl.style.display = "block";
  }
}

export function hide(): void {
  if (panelEl) {
    panelEl.style.display = "none";
  }
}

export function addStep(label: string, status: TimelineStepStatus): void {
  if (!stepsContainer) return;
  show();

  const time = formatTime();
  const el = createStepEl(label, status, time);
  stepsContainer.appendChild(el);
  steps.push({ label, status, time, el });
}

export function updateStep(label: string, newStatus: TimelineStepStatus): void {
  const step = steps.find((s) => s.label === label);
  if (!step) {
    addStep(label, newStatus);
    return;
  }

  step.status = newStatus;
  step.el.className = `timeline-step timeline-step--${newStatus}`;
}

export function finalize(): void {
  for (const step of steps) {
    if (step.status === "active") {
      updateStep(step.label, "done");
    }
  }
}

export function clear(): void {
  steps.length = 0;
  if (stepsContainer) {
    stepsContainer.innerHTML = "";
  }
}
