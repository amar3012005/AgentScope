import { createElement, escapeHtml } from "../utils/dom";

const SUGGESTIONS = [
  "Create a pitch deck for DaVinci AI",
  "Analyze our GraphRAG performance",
  "Design a landing page",
  "Generate a quarterly report",
];

let welcomeEl: HTMLElement | null = null;

export function mountWelcome(
  container: HTMLElement,
  onSuggestion: (text: string) => void
): void {
  welcomeEl = createElement("div", { class: "welcome" });

  const greeting = createElement("h1", { class: "welcome-greeting" });
  greeting.innerHTML = `Hello. What can I <span class="welcome-greeting-accent">build</span> for you?`;

  const subtitle = createElement("p", { class: "welcome-subtitle" }, [
    "Describe what you need and BLAIQ will orchestrate the right agents to deliver it.",
  ]);

  const chips = createElement("div", { class: "welcome-chips" });
  for (const suggestion of SUGGESTIONS) {
    const chip = createElement("button", { class: "welcome-chip", type: "button" }, [
      escapeHtml(suggestion),
    ]);
    chip.addEventListener("click", () => {
      onSuggestion(suggestion);
    });
    chips.appendChild(chip);
  }

  const version = createElement("div", { class: "welcome-version" }, ["BLAIQ Core v4.0"]);

  welcomeEl.appendChild(greeting);
  welcomeEl.appendChild(subtitle);
  welcomeEl.appendChild(chips);
  welcomeEl.appendChild(version);

  container.appendChild(welcomeEl);
}

export function show(): void {
  if (welcomeEl) {
    welcomeEl.style.display = "flex";
  }
}

export function hide(): void {
  if (welcomeEl) {
    welcomeEl.style.display = "none";
  }
}
