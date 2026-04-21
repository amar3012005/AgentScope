import { createElement, escapeHtml } from "../utils/dom";
import { state, subscribe } from "../state";
import { mountUpload } from "./upload";
import { mountSession } from "./session";

interface AgentDef {
  id: string;
  name: string;
  status: string;
}

const AGENTS: AgentDef[] = [
  { id: "echo", name: "Echo Agent", status: "debug" },
  { id: "content_creator", name: "Content Creator", status: "vangogh" },
];

let agentTilesContainer: HTMLElement | null = null;

function renderAgentTiles(): void {
  if (!agentTilesContainer) return;
  agentTilesContainer.innerHTML = "";

  for (const agent of AGENTS) {
    const isActive = state.currentAgent === agent.id;
    const tile = createElement("button", {
      class: `agent-tile${isActive ? " active" : ""}`,
      type: "button",
      "data-agent": agent.id,
    });

    const dot = createElement("span", { class: "agent-tile-dot" });
    const name = createElement("span", { class: "agent-tile-name" }, [
      escapeHtml(agent.name),
    ]);
    const status = createElement("span", { class: "agent-tile-status" }, [
      escapeHtml(agent.status),
    ]);

    tile.appendChild(dot);
    tile.appendChild(name);
    tile.appendChild(status);

    tile.addEventListener("click", () => {
      state.currentAgent = agent.id;
    });

    agentTilesContainer.appendChild(tile);
  }
}

export function mountSidebar(container: HTMLElement): void {
  // Header with logo
  const header = createElement("div", { class: "sidebar-header" });
  const logo = createElement("div", { class: "sidebar-logo" });
  logo.innerHTML = `BLAI<span class="sidebar-logo-accent">Q</span>`;
  header.appendChild(logo);

  // Agent tiles section
  const agentsSection = createElement("div", { class: "sidebar-section" });
  const agentsTitle = createElement("div", { class: "sidebar-section-title" }, ["Agents"]);
  agentTilesContainer = createElement("div", { class: "agent-tiles" });

  agentsSection.appendChild(agentsTitle);
  agentsSection.appendChild(agentTilesContainer);

  // Nav area
  const nav = createElement("nav", { class: "sidebar-nav" });

  // Upload zone
  const uploadContainer = createElement("div", { class: "sidebar-section" });
  const uploadTitle = createElement("div", { class: "sidebar-section-title" }, ["Files"]);
  uploadContainer.appendChild(uploadTitle);
  mountUpload(uploadContainer);

  // Session history
  const sessionSection = createElement("div", { class: "sidebar-footer" });
  const sessionTitle = createElement("div", { class: "sidebar-section-title" }, [
    "Recent Sessions",
  ]);
  sessionSection.appendChild(sessionTitle);
  mountSession(sessionSection);

  container.appendChild(header);
  container.appendChild(agentsSection);
  container.appendChild(nav);
  container.appendChild(uploadContainer);
  container.appendChild(sessionSection);

  renderAgentTiles();

  subscribe("currentAgent", () => {
    renderAgentTiles();
  });
}
