import { createElement, escapeHtml } from "../utils/dom";
import { formatFileSize } from "../utils/format";
import { CONFIG } from "../config";

interface UploadedFile {
  name: string;
  size: number;
  status: "uploading" | "success" | "error";
  message?: string;
}

const ACCEPTED_TYPES = [".pdf", ".docx", ".txt", ".md"];
const MAX_SIZE = 50 * 1024 * 1024; // 50MB

let zoneEl: HTMLElement | null = null;
let fileListEl: HTMLElement | null = null;
let progressEl: HTMLElement | null = null;
const uploadedFiles: UploadedFile[] = [];

function renderFileList(): void {
  if (!fileListEl) return;
  fileListEl.innerHTML = "";

  if (uploadedFiles.length === 0) return;

  for (const file of uploadedFiles) {
    const item = createElement("div", { class: "upload-file-item" });

    const statusDot = createElement("div", {
      class: `upload-file-status upload-file-status--${file.status}`,
    });

    const info = createElement("div", { class: "upload-file-info" });
    const name = createElement("div", { class: "upload-file-name" }, [escapeHtml(file.name)]);
    const size = createElement("div", { class: "upload-file-size" }, [formatFileSize(file.size)]);
    info.appendChild(name);
    info.appendChild(size);

    item.appendChild(statusDot);
    item.appendChild(info);

    fileListEl.appendChild(item);
  }
}

function showProgress(percent: number, label: string): void {
  if (!progressEl) return;
  progressEl.style.display = "block";
  progressEl.innerHTML = "";

  const bar = createElement("div", { class: "upload-progress-bar" });
  const fill = createElement("div", { class: "upload-progress-fill" });
  fill.style.width = `${percent}%`;
  bar.appendChild(fill);

  const labelRow = createElement("div", { class: "upload-progress-label" });
  const labelText = createElement("span", {}, [escapeHtml(label)]);
  const percentText = createElement("span", {}, [`${Math.round(percent)}%`]);
  labelRow.appendChild(labelText);
  labelRow.appendChild(percentText);

  progressEl.appendChild(bar);
  progressEl.appendChild(labelRow);
}

function hideProgress(): void {
  if (progressEl) {
    progressEl.style.display = "none";
  }
}

function isAcceptedType(filename: string): boolean {
  const lower = filename.toLowerCase();
  return ACCEPTED_TYPES.some((ext) => lower.endsWith(ext));
}

async function uploadFile(file: File): Promise<void> {
  if (!isAcceptedType(file.name)) {
    uploadedFiles.push({
      name: file.name,
      size: file.size,
      status: "error",
      message: "Unsupported file type",
    });
    renderFileList();
    return;
  }

  if (file.size > MAX_SIZE) {
    uploadedFiles.push({
      name: file.name,
      size: file.size,
      status: "error",
      message: "File too large (max 50MB)",
    });
    renderFileList();
    return;
  }

  const entry: UploadedFile = {
    name: file.name,
    size: file.size,
    status: "uploading",
  };
  uploadedFiles.push(entry);
  renderFileList();
  showProgress(0, `Uploading ${file.name}...`);

  const formData = new FormData();
  formData.append("file", file);
  formData.append("tenant_id", CONFIG.TENANT_ID);

  try {
    const headers: Record<string, string> = {};
    if (CONFIG.API_KEY) {
      headers["X-API-Key"] = CONFIG.API_KEY;
    }

    const response = await fetch(`${CONFIG.API_BASE}/upload`, {
      method: "POST",
      headers,
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`Upload failed: ${response.status}`);
    }

    entry.status = "success";
    showProgress(100, "Upload complete");
    setTimeout(hideProgress, 2000);
  } catch (err) {
    entry.status = "error";
    entry.message = err instanceof Error ? err.message : "Upload failed";
    hideProgress();
  }

  renderFileList();
}

function handleFiles(files: FileList | null): void {
  if (!files) return;
  for (let i = 0; i < files.length; i++) {
    uploadFile(files[i]);
  }
}

export function mountUpload(container: HTMLElement): void {
  zoneEl = createElement("div", {
    class: "sidebar-upload",
    role: "button",
    tabindex: "0",
    "aria-label": "Upload files",
  });

  const text = createElement("div", { class: "sidebar-upload-text" });
  text.innerHTML = `Drop files here or <span class="upload-zone-browse">browse</span>`;

  const hint = createElement("div", { class: "upload-zone-hint" }, [
    ".pdf, .docx, .txt, .md (max 50MB)",
  ]);

  const fileInput = createElement("input", {
    type: "file",
    accept: ACCEPTED_TYPES.join(","),
    multiple: "true",
    style: "display:none",
    "aria-hidden": "true",
  }) as HTMLInputElement;

  zoneEl.appendChild(text);
  zoneEl.appendChild(hint);
  zoneEl.appendChild(fileInput);

  progressEl = createElement("div", { class: "upload-progress", style: "display:none" });
  fileListEl = createElement("div", { class: "upload-file-list" });

  zoneEl.addEventListener("click", () => {
    fileInput.click();
  });

  zoneEl.addEventListener("keydown", (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });

  fileInput.addEventListener("change", () => {
    handleFiles(fileInput.files);
    fileInput.value = "";
  });

  zoneEl.addEventListener("dragover", (e: DragEvent) => {
    e.preventDefault();
    zoneEl?.classList.add("upload-zone--dragover");
  });

  zoneEl.addEventListener("dragleave", () => {
    zoneEl?.classList.remove("upload-zone--dragover");
  });

  zoneEl.addEventListener("drop", (e: DragEvent) => {
    e.preventDefault();
    zoneEl?.classList.remove("upload-zone--dragover");
    handleFiles(e.dataTransfer?.files ?? null);
  });

  container.appendChild(zoneEl);
  container.appendChild(progressEl);
  container.appendChild(fileListEl);
}
