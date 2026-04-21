import { createElement } from "../utils/dom";
import { state, subscribe } from "../state";

const SUGGESTION_CHIPS = [
  "Create a pitch deck",
  "Analyze our data",
  "Generate a report",
];

let textareaEl: HTMLTextAreaElement | null = null;
let sendBtn: HTMLButtonElement | null = null;
let suggestionsEl: HTMLElement | null = null;

function updateSendButton(): void {
  if (!sendBtn || !textareaEl) return;
  sendBtn.disabled = !textareaEl.value.trim() || state.isProcessing;
}

function autoResize(): void {
  if (!textareaEl) return;
  textareaEl.style.height = "auto";
  const newHeight = Math.min(textareaEl.scrollHeight, 200);
  textareaEl.style.height = `${newHeight}px`;
}

export function mountInput(
  container: HTMLElement,
  onSend: (text: string) => void
): void {
  const wrapper = createElement("div", { class: "input-wrapper" });

  suggestionsEl = createElement("div", { class: "input-suggestions" });
  for (const chip of SUGGESTION_CHIPS) {
    const btn = createElement("button", { class: "input-chip", type: "button" }, [chip]);
    btn.addEventListener("click", () => {
      onSend(chip);
    });
    suggestionsEl.appendChild(btn);
  }

  const row = createElement("div", { class: "input-row" });

  textareaEl = createElement("textarea", {
    class: "input-textarea",
    placeholder: "Ask BLAIQ anything...",
    rows: "1",
    "aria-label": "Message input",
  });

  sendBtn = createElement("button", {
    class: "input-send",
    type: "button",
    "aria-label": "Send message",
    disabled: "true",
  }) as HTMLButtonElement;

  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", "18");
  svg.setAttribute("height", "18");
  const path = document.createElementNS(svgNS, "path");
  path.setAttribute("d", "M2.01 21L23 12 2.01 3 2 10l15 2-15 2z");
  path.setAttribute("fill", "white");
  svg.appendChild(path);
  sendBtn.appendChild(svg);

  function doSend(): void {
    if (!textareaEl) return;
    const text = textareaEl.value.trim();
    if (!text || state.isProcessing) return;
    textareaEl.value = "";
    autoResize();
    updateSendButton();
    if (suggestionsEl) {
      suggestionsEl.style.display = "none";
    }
    onSend(text);
  }

  textareaEl.addEventListener("input", () => {
    updateSendButton();
    autoResize();
  });

  textareaEl.addEventListener("keydown", (e: KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      doSend();
    }
  });

  sendBtn.addEventListener("click", doSend);

  row.appendChild(textareaEl);
  row.appendChild(sendBtn);

  wrapper.appendChild(suggestionsEl);
  wrapper.appendChild(row);
  container.appendChild(wrapper);

  subscribe("isProcessing", () => {
    updateSendButton();
  });
}
