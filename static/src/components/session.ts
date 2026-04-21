import { createElement, escapeHtml } from "../utils/dom";
import { truncate, formatTime } from "../utils/format";
import { apiGet } from "../api/client";
import { state } from "../state";

interface SessionEntry {
  threadId: string;
  title: string;
  status: string;
  time: string;
}

const STORAGE_KEY = "blaiq_sessions";
let listEl: HTMLElement | null = null;
let entries: SessionEntry[] = [];

function loadEntries(): SessionEntry[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as SessionEntry[];
  } catch {
    return [];
  }
}

function saveEntries(): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
  } catch {
    // Storage unavailable
  }
}

function getStatusDotClass(status: string): string {
  switch (status) {
    case "complete":
      return "session-dot--active";
    case "paused":
    case "hitl_required":
      return "session-dot--idle";
    case "error":
    case "failed":
      return "session-dot--error";
    default:
      return "session-dot--ended";
  }
}

function renderEntries(): void {
  if (!listEl) return;
  listEl.innerHTML = "";

  if (entries.length === 0) {
    const empty = createElement("div", { class: "session-empty" }, ["No recent sessions"]);
    listEl.appendChild(empty);
    return;
  }

  for (const entry of entries) {
    const item = createElement("button", {
      class: `session-item${entry.threadId === state.threadId ? " active" : ""}`,
      type: "button",
    });

    const dot = createElement("span", {
      class: `session-dot ${getStatusDotClass(entry.status)}`,
      "aria-label": entry.status,
    });

    const content = createElement("div", { class: "session-content" });
    const title = createElement("div", { class: "session-title" }, [
      escapeHtml(truncate(entry.title, 28)),
    ]);
    const timestamp = createElement("div", { class: "session-timestamp" }, [entry.time]);
    content.appendChild(title);
    content.appendChild(timestamp);

    item.appendChild(dot);
    item.appendChild(content);

    item.addEventListener("click", () => {
      loadThread(entry.threadId);
    });

    listEl.appendChild(item);
  }
}

async function loadThread(threadId: string): Promise<void> {
  try {
    const response = await apiGet(`/api/v4/orchestrator/status/${threadId}`);
    const data = await response.json();
    state.threadId = threadId;
    if (data.final_artifact) {
      state.lastFinalArtifact = data.final_artifact;
    }
  } catch {
    // Failed to load thread
  }
}

export function mountSession(container: HTMLElement): void {
  entries = loadEntries();
  listEl = createElement("div", { class: "session-list" });
  renderEntries();
  container.appendChild(listEl);
}

export function addEntry(threadId: string, title: string, status: string): void {
  const existing = entries.findIndex((e) => e.threadId === threadId);
  const newEntry: SessionEntry = {
    threadId,
    title,
    status,
    time: formatTime(),
  };

  if (existing >= 0) {
    entries[existing] = newEntry;
  } else {
    entries.unshift(newEntry);
  }

  if (entries.length > 20) {
    entries = entries.slice(0, 20);
  }

  saveEntries();
  renderEntries();
}
