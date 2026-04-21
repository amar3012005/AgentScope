import { createElement, escapeHtml } from "../utils/dom";
import { generateId } from "../utils/format";
import { state } from "../state";
import type { Message } from "../types";

let messagesEl: HTMLElement | null = null;
let containerEl: HTMLElement | null = null;

function createMessageEl(msg: Message): HTMLElement {
  const wrapper = createElement("div", {
    class: `message message--${msg.sender}`,
    "data-id": msg.id,
  });

  const avatar = createElement("div", { class: "message-avatar" });
  if (msg.sender === "user") {
    avatar.textContent = "U";
  } else if (msg.sender === "assistant") {
    avatar.textContent = msg.agentName ? msg.agentName.charAt(0).toUpperCase() : "A";
  } else {
    avatar.textContent = "S";
  }

  const bubble = createElement("div", { class: "message-bubble" });

  if (msg.sender === "assistant" && msg.agentName) {
    const sender = createElement("div", {
      class: "message-sender message-sender--agent",
    }, [escapeHtml(msg.agentName)]);
    bubble.appendChild(sender);
  }

  if (msg.htmlContent) {
    const textContainer = createElement("div", { class: "message-text" }, [
      "Content artifact generated. See preview below.",
    ]);
    bubble.appendChild(textContainer);

    const htmlContainer = createElement("div", { class: "message-html-container" });
    const iframe = createElement("iframe", {
      sandbox: "allow-scripts allow-same-origin",
      title: "Content artifact",
    });
    // Don't sanitize iframe srcdoc — the sandbox attribute provides isolation.
    // DOMPurify strips <script> tags which Tailwind CSS needs.
    iframe.srcdoc = msg.htmlContent;
    iframe.addEventListener("load", () => {
      try {
        const doc = iframe.contentDocument;
        if (doc) {
          iframe.style.height = `${doc.documentElement.scrollHeight}px`;
        }
      } catch {
        iframe.style.height = "400px";
      }
    });
    htmlContainer.appendChild(iframe);
    bubble.appendChild(htmlContainer);
  } else {
    const textEl = createElement("div", { class: "message-text" });
    textEl.innerHTML = escapeHtml(msg.text).replace(/\n/g, "<br>");
    bubble.appendChild(textEl);
  }

  const time = createElement("div", { class: "message-time" }, [
    new Date(msg.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
  ]);
  bubble.appendChild(time);

  if (msg.sender !== "system") {
    wrapper.appendChild(avatar);
  }
  wrapper.appendChild(bubble);

  return wrapper;
}

function scrollToBottom(): void {
  if (containerEl) {
    containerEl.scrollTop = containerEl.scrollHeight;
  }
}

export function mountChat(container: HTMLElement): void {
  containerEl = container;
  messagesEl = createElement("div", { class: "messages-list", id: "messages" });
  container.appendChild(messagesEl);
}

export function addTextMessage(
  text: string,
  sender: "user" | "assistant" | "system",
  agentName?: string
): void {
  const msg: Message = {
    id: generateId(),
    sender,
    text,
    agentName,
    timestamp: Date.now(),
  };
  state.messages = [...state.messages, msg];

  if (messagesEl) {
    messagesEl.appendChild(createMessageEl(msg));
    scrollToBottom();
  }
}

export function addHtmlMessage(html: string, agentName: string): void {
  const msg: Message = {
    id: generateId(),
    sender: "assistant",
    text: "",
    htmlContent: html,
    agentName,
    timestamp: Date.now(),
  };
  state.messages = [...state.messages, msg];

  if (messagesEl) {
    messagesEl.appendChild(createMessageEl(msg));
    scrollToBottom();
  }
}

export function clearChat(): void {
  state.messages = [];
  if (messagesEl) {
    messagesEl.innerHTML = "";
  }
}
