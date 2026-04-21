import { createElement } from "../utils/dom";

type ViewMode = "desktop" | "tablet" | "mobile";

let containerEl: HTMLElement | null = null;
let frameWrapper: HTMLElement | null = null;
let iframeEl: HTMLIFrameElement | null = null;
let modeButtons: Map<ViewMode, HTMLElement> = new Map();
let currentHtml = "";

function setMode(mode: ViewMode): void {
  if (!frameWrapper) return;

  frameWrapper.className = `artifact-frame-wrapper artifact-frame-wrapper--${mode}`;

  modeButtons.forEach((btn, m) => {
    if (m === mode) {
      btn.classList.add("active");
    } else {
      btn.classList.remove("active");
    }
  });
}

function adjustIframeHeight(): void {
  if (!iframeEl) return;
  try {
    const doc = iframeEl.contentDocument;
    if (doc) {
      const height = doc.documentElement.scrollHeight;
      iframeEl.style.height = `${Math.max(height, 400)}px`;
    }
  } catch {
    iframeEl.style.height = "500px";
  }
}

export function mountArtifact(container: HTMLElement): void {
  containerEl = createElement("div", {
    class: "artifact-container",
    style: "display:none",
  });

  // Toolbar
  const toolbar = createElement("div", { class: "artifact-toolbar" });
  const toolbarLeft = createElement("div", { class: "artifact-toolbar-left" });
  const toolbarRight = createElement("div", { class: "artifact-toolbar-right" });

  const label = createElement("span", { class: "artifact-label" }, ["Artifact Preview"]);

  // Mode switcher
  const switcher = createElement("div", { class: "artifact-mode-switcher" });
  const modes: { mode: ViewMode; icon: string; label: string }[] = [
    { mode: "desktop", icon: "\uD83D\uDDA5", label: "Desktop" },
    { mode: "tablet", icon: "\uD83D\uDCF1", label: "Tablet" },
    { mode: "mobile", icon: "\uD83D\uDCF2", label: "Mobile" },
  ];

  for (const m of modes) {
    const btn = createElement("button", {
      class: `artifact-mode-btn${m.mode === "desktop" ? " active" : ""}`,
      type: "button",
      "aria-label": `${m.label} view`,
    });
    const iconSpan = createElement("span", { class: "icon" }, [m.icon]);
    const labelSpan = createElement("span", { class: "artifact-mode-label" }, [m.label]);
    btn.appendChild(iconSpan);
    btn.appendChild(labelSpan);
    btn.addEventListener("click", () => setMode(m.mode));
    modeButtons.set(m.mode, btn);
    switcher.appendChild(btn);
  }

  // Action buttons
  const newTabBtn = createElement("button", {
    class: "artifact-action-btn",
    type: "button",
    "aria-label": "Open in new tab",
    title: "Open in new tab",
  }, ["\u2197"]);

  const downloadBtn = createElement("button", {
    class: "artifact-action-btn",
    type: "button",
    "aria-label": "Download",
    title: "Download",
  }, ["\u2B07"]);

  const copyBtn = createElement("button", {
    class: "artifact-action-btn",
    type: "button",
    "aria-label": "Copy HTML",
    title: "Copy HTML",
  }, ["\uD83D\uDCCB"]);

  newTabBtn.addEventListener("click", () => {
    if (!currentHtml) return;
    const win = window.open("", "_blank");
    if (win) {
      win.document.write(currentHtml);
      win.document.close();
    }
  });

  downloadBtn.addEventListener("click", () => {
    if (!currentHtml) return;
    const blob = new Blob([currentHtml], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    const a = createElement("a", { href: url, download: "artifact.html" });
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  });

  copyBtn.addEventListener("click", () => {
    if (!currentHtml) return;
    navigator.clipboard.writeText(currentHtml).catch(() => {
      // Clipboard write failed
    });
  });

  toolbarLeft.appendChild(label);
  toolbarLeft.appendChild(switcher);
  toolbarRight.appendChild(newTabBtn);
  toolbarRight.appendChild(downloadBtn);
  toolbarRight.appendChild(copyBtn);

  toolbar.appendChild(toolbarLeft);
  toolbar.appendChild(toolbarRight);

  // Preview area
  const preview = createElement("div", { class: "artifact-preview" });
  frameWrapper = createElement("div", {
    class: "artifact-frame-wrapper artifact-frame-wrapper--desktop",
  });

  iframeEl = createElement("iframe", {
    class: "artifact-iframe",
    sandbox: "allow-scripts allow-same-origin",
    title: "Artifact preview",
  }) as HTMLIFrameElement;

  iframeEl.addEventListener("load", adjustIframeHeight);

  frameWrapper.appendChild(iframeEl);
  preview.appendChild(frameWrapper);

  containerEl.appendChild(toolbar);
  containerEl.appendChild(preview);
  container.appendChild(containerEl);
}

export function render(html: string): void {
  currentHtml = html;
  if (!containerEl || !iframeEl) return;

  containerEl.style.display = "flex";
  // Don't sanitize — iframe sandbox provides isolation.
  // DOMPurify strips <script> tags needed by Tailwind CSS.
  iframeEl.srcdoc = html;

  setTimeout(adjustIframeHeight, 500);
}

export function hide(): void {
  if (containerEl) {
    containerEl.style.display = "none";
  }
}
