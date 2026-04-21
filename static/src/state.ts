import type { Message, ContentSchema, FinalArtifact } from "./types";

export interface AppState {
  threadId: string;
  sessionId: string;
  messages: Message[];
  isProcessing: boolean;
  currentAgent: string;
  timelineVisible: boolean;
  hitlVisible: boolean;
  hitlQuestions: string[];
  hitlThreadId: string;
  hitlAgentNode: string;
  schemaVisible: boolean;
  schema: ContentSchema | null;
  lastArtifactHtml: string;
  lastFinalArtifact: FinalArtifact | null;
}

const PERSIST_KEYS: (keyof AppState)[] = ["threadId", "sessionId"];
const STORAGE_KEY = "blaiq_state";

function getDefaults(): AppState {
  return {
    threadId: "",
    sessionId: "",
    messages: [],
    isProcessing: false,
    currentAgent: "",
    timelineVisible: false,
    hitlVisible: false,
    hitlQuestions: [],
    hitlThreadId: "",
    hitlAgentNode: "",
    schemaVisible: false,
    schema: null,
    lastArtifactHtml: "",
    lastFinalArtifact: null,
  };
}

function createStore(initial: AppState): AppState {
  return new Proxy(initial, {
    set(target: AppState, prop: string | symbol, value: unknown): boolean {
      const key = prop as keyof AppState;
      if (key in target) {
        (target as unknown as Record<string, unknown>)[key as string] = value;
        window.dispatchEvent(
          new CustomEvent(`state:${String(key)}`, { detail: value })
        );
        return true;
      }
      return false;
    },
  });
}

export const state: AppState = createStore(getDefaults());

export function subscribe<K extends keyof AppState>(
  key: K,
  callback: (value: AppState[K]) => void
): () => void {
  const handler = (e: Event): void => {
    callback((e as CustomEvent).detail as AppState[K]);
  };
  window.addEventListener(`state:${String(key)}`, handler);
  return () => window.removeEventListener(`state:${String(key)}`, handler);
}

export function persist(): void {
  try {
    const data: Record<string, unknown> = {};
    for (const key of PERSIST_KEYS) {
      data[key] = state[key];
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch {
    // Storage unavailable — silently degrade
  }
}

export function restore(): void {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const data = JSON.parse(raw) as Partial<AppState>;
    for (const key of PERSIST_KEYS) {
      if (data[key] !== undefined) {
        (state as unknown as Record<string, unknown>)[key as string] = data[key];
      }
    }
  } catch {
    // Corrupt storage — start fresh
  }
}
