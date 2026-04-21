import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { normalizeArtifactHtml } from "../../shared/orchestrator/html";
import { formatTimelineTime } from "../../shared/orchestrator/timeline";
import { useOrchestratorStore } from "../../shared/orchestrator/store";
import type {
  ContentSchema,
  ChatMessage,
  TimelineStepStatus,
} from "../../shared/orchestrator/types";

type RailTab = "preview" | "plan" | "schema" | "governance";

function statusTone(status: TimelineStepStatus): string {
  switch (status) {
    case "active":
      return "timeline-step--active";
    case "done":
      return "timeline-step--done";
    case "blocked":
      return "timeline-step--blocked";
    case "warning":
      return "timeline-step--warning";
    case "failed":
      return "timeline-step--failed";
    default:
      return "";
  }
}

function quickChips(question: string): string[] {
  const lower = question.toLowerCase();
  if (lower.includes("audience") || lower.includes("target")) {
    return ["C-suite and board", "Enterprise buyers", "Sales leadership", "Investors"];
  }
  if (
    lower.includes("kpi") ||
    lower.includes("metric") ||
    lower.includes("revenue") ||
    lower.includes("growth") ||
    lower.includes("margin")
  ) {
    return ["Revenue growth", "Gross margin", "CAC payback", "Pipeline conversion"];
  }
  if (
    lower.includes("narrative") ||
    lower.includes("goal") ||
    lower.includes("board") ||
    lower.includes("investor") ||
    lower.includes("sales strategy")
  ) {
    return ["Board review", "Investor update", "Sales strategy", "Executive briefing"];
  }
  if (lower.includes("style") || lower.includes("design") || lower.includes("tone") || lower.includes("visual")) {
    return ["Monochrome editorial", "Modern minimal", "Corporate clean", "Dense analytical"];
  }
  if (lower.includes("format") || lower.includes("output")) {
    return ["Pitch deck", "Dashboard", "Landing page", "Report"];
  }
  if (lower.includes("evidence") || lower.includes("data")) {
    return ["Use all available", "Latest only", "Key metrics", "Custom"];
  }
  if (lower.includes("timeline") || lower.includes("period") || lower.includes("timeframe")) {
    return ["Last 12 months", "Quarterly view", "Year over year", "Current quarter"];
  }
  return [];
}

function parseMultilineList(value: string): string[] {
  return value
    .split(/[\n,]/g)
    .map((item) => item.trim())
    .filter(Boolean);
}

function listToMultiline(values: string[]): string {
  return values.join("\n");
}

function splitThinkingBlock(text: string): { thinking?: string; body: string } {
  const match = text.match(/<thinking>([\s\S]*?)<\/thinking>/i);
  if (!match) {
    return { body: text };
  }
  const thinking = match[1].trim();
  const body = text.replace(match[0], "").trim();
  return { thinking, body };
}

function renderMarkdownHtml(text: string): string {
  marked.setOptions({
    gfm: true,
    breaks: true,
  });
  const rawHtml = marked.parse(text) as string;
  return DOMPurify.sanitize(rawHtml);
}

function findTimelineStatus(labels: string[], query: string): TimelineStepStatus | "idle" {
  const match = labels.find((label) => label.toLowerCase().includes(query.toLowerCase()));
  if (!match) {
    return "idle";
  }
  return "done";
}

function phaseLabelFromState(
  loadingLabel: string,
  artifactKind: string,
  sectionCount: number,
  totalSections: number
): string {
  if (loadingLabel) {
    return loadingLabel;
  }
  if (sectionCount > 0 && totalSections > 0 && sectionCount < totalSections) {
    return `Rendering section ${sectionCount + 1}/${totalSections}`;
  }
  if (artifactKind) {
    return `Preparing ${artifactKind}`;
  }
  return "Preparing artifact";
}

function TimelineView(): JSX.Element {
  const { state } = useOrchestratorStore();

  return (
    <section className="timeline-panel" aria-label="Execution plan">
      <div className="rail-panel__header">
        <div>
          <div className="rail-panel__eyebrow">Plan</div>
          <h3 className="rail-panel__title">Execution path</h3>
        </div>
      </div>
      <div className="timeline-steps">
        {state.timeline.length === 0 ? (
          <div className="rail-empty">The plan will appear here once Core routes a workflow.</div>
        ) : (
          state.timeline.map((entry) => (
            <div
              key={entry.id}
              className={`timeline-step timeline-step--${entry.status} ${statusTone(entry.status)}`}
            >
              <div className="timeline-step-dot" />
              <div className="timeline-step-content">
                <div className="timeline-step-label">{entry.label}</div>
                <div className="timeline-step-time">{formatTimelineTime(entry.timestamp)}</div>
                {entry.detail ? <div className="timeline-step-detail">{entry.detail}</div> : null}
                {entry.data ? (
                  <div className="timeline-step-meta" aria-label="Step metadata">
                    {Object.entries(entry.data).map(([key, value]) => (
                      <span className="timeline-step-meta-item" key={`${entry.id}-${key}`}>
                        <span className="timeline-step-meta-key">{key}</span>
                        <span className="timeline-step-meta-value">{value}</span>
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

function GovernancePanel(): JSX.Element {
  const { state } = useOrchestratorStore();
  const report = state.governance.report;

  return (
    <section className="rail-panel governance-shell">
      <div className="rail-panel__header">
        <div>
          <div className="rail-panel__eyebrow">Governance</div>
          <h3 className="rail-panel__title">Review summary</h3>
        </div>
      </div>
      {!report ? (
        <div className="rail-empty">Policy checks will appear here after rendering finishes.</div>
      ) : (
        <div className="governance-detail governance-detail--embedded">
          <div className="governance-summary-row">
            <span className={`governance-badge ${report.validation_passed ? "governance-badge--passed" : "governance-badge--failed"}`}>
              {report.validation_passed ? "Passed" : "Attention needed"}
            </span>
            <span className="governance-summary-text">
              {report.policy_checks.length} checks
            </span>
            <span className="governance-summary-text">
              {report.violations.length} violation(s)
            </span>
          </div>
          <div className="governance-checks">
            {report.policy_checks.map((check) => (
              <div key={`${check.rule}-${check.detail}`} className="governance-check-row">
                <div
                  className={`governance-check-icon governance-check-icon--${
                    check.passed ? "passed" : "failed"
                  }`}
                >
                  {check.passed ? "✓" : "!"}
                </div>
                <div className="governance-check-content">
                  <div className="governance-check-rule">{check.rule}</div>
                  <div className="governance-check-detail">{check.detail}</div>
                </div>
              </div>
            ))}
          </div>
          {report.violations.length > 0 ? (
            <div className="governance-violations">
              <div className="governance-violations-label">Violations</div>
              {report.violations.map((violation) => (
                <div key={violation} className="governance-violation-item">
                  {violation}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}

function ArtifactPreview(): JSX.Element {
  const { state, dispatch } = useOrchestratorStore();
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const [viewMode, setViewMode] = useState<"desktop" | "tablet" | "mobile">("desktop");
  const html = normalizeArtifactHtml(state.artifact.html);
  const showPreview = Boolean(state.artifact.visible && state.artifact.html);
  const renderedSections = state.artifact.sections?.length ?? 0;
  const totalSections = state.artifact.totalSections ?? 0;
  const isRendering = Boolean(state.artifact.loading) || totalSections > 0;
  const currentSectionCount = totalSections > 0
    ? Math.min(renderedSections + (state.artifact.loading ? 1 : 0), totalSections)
    : renderedSections;
  const phase = phaseLabelFromState(
    state.artifact.loadingLabel || "",
    state.artifact.artifactKind || "",
    renderedSections,
    totalSections
  );
  const planLabels = state.timeline.map((entry) => entry.label);
  const planStates = [
    { label: "Planner", state: findTimelineStatus(planLabels, "plan") },
    { label: "GraphRAG", state: findTimelineStatus(planLabels, "evidence") },
    {
      label: "Vangogh",
      state: isRendering || Boolean(state.artifact.html)
        ? (state.artifact.loading ? "active" : "done")
        : "idle",
    },
    {
      label: "Governance",
      state: state.governance.report ? "done" : findTimelineStatus(planLabels, "governance"),
    },
  ] as const;

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;

    const resize = (): void => {
      try {
        const doc = iframe.contentDocument;
        if (!doc) return;
        iframe.style.height = `${Math.max(doc.documentElement.scrollHeight, 520)}px`;
      } catch {
        iframe.style.height = "640px";
      }
    };

    resize();
    iframe.addEventListener("load", resize);
    return () => iframe.removeEventListener("load", resize);
  }, [html]);

  const actions = useMemo(
    () => ({
      openNewTab(): void {
        if (!state.artifact.html) return;
        const win = window.open("", "_blank");
        if (win) {
          win.document.write(html);
          win.document.close();
        }
      },
      download(): void {
        if (!state.artifact.html) return;
        const blob = new Blob([html], { type: "text/html" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "artifact.html";
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
      },
      copy(): void {
        if (!state.artifact.html) return;
        navigator.clipboard.writeText(html).catch(() => {
          // Ignore clipboard failures.
        });
      },
    }),
    [html, state.artifact.html]
  );

  return (
    <section className="artifact-container">
      <div className="artifact-toolbar">
        <div className="artifact-toolbar-left">
          <div>
            <span className="artifact-label">Preview</span>
            <div className="artifact-title">{state.artifact.title || "Artifact preview"}</div>
          </div>
          <div className="artifact-mode-switcher">
            {(["desktop", "tablet", "mobile"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                className={`artifact-mode-btn${viewMode === mode ? " active" : ""}`}
                onClick={() => setViewMode(mode)}
                aria-label={`${mode} view`}
              >
                {mode}
              </button>
            ))}
          </div>
        </div>
        <div className="artifact-toolbar-right">
          <button
            className="artifact-action-btn"
            type="button"
            title="Close preview"
            aria-label="Close preview"
            onClick={() => dispatch({ type: "set-artifact", payload: { visible: false } })}
          >
            ×
          </button>
          <button className="artifact-action-btn" type="button" title="Open in new tab" aria-label="Open in new tab" onClick={actions.openNewTab}>
            ↗
          </button>
          <button className="artifact-action-btn" type="button" title="Download" aria-label="Download" onClick={actions.download}>
            ⬇
          </button>
          <button className="artifact-action-btn" type="button" title="Copy HTML" aria-label="Copy HTML" onClick={actions.copy}>
            ⧉
          </button>
        </div>
      </div>

      {!showPreview ? (
        <div className="artifact-preview artifact-preview--empty">
          {isRendering ? (
            <div className="artifact-rendering-shell" aria-live="polite">
              <div className="artifact-rendering-header">
                <span className="artifact-rendering-kicker">Rendering</span>
                <h3 className="artifact-rendering-title">Vangogh is building the artifact</h3>
                <p className="artifact-rendering-copy">{phase}</p>
              </div>
              <div className="artifact-rendering-progress">
                <div className="artifact-rendering-progress-row">
                  <span>Phase</span>
                  <strong>{state.artifact.artifactKind || "content"}</strong>
                </div>
                <div className="artifact-rendering-progress-row">
                  <span>Progress</span>
                  <strong>{totalSections > 0 ? `${currentSectionCount}/${totalSections}` : "Starting"}</strong>
                </div>
                {renderedSections > 0 ? (
                  <div className="artifact-rendering-progress-row">
                    <span>Latest section</span>
                    <strong>{state.artifact.sections?.[state.artifact.sections.length - 1]?.label || "Section ready"}</strong>
                  </div>
                ) : null}
              </div>
              <div className="artifact-rendering-track">
                {planStates.map((item) => (
                  <span
                    key={item.label}
                    className={`artifact-rendering-step artifact-rendering-step--${item.state}`}
                  >
                    {item.label}
                  </span>
                ))}
              </div>
              <div className="artifact-rendering-preview-card">
                <div className="artifact-rendering-preview-bar" />
                <div className="artifact-rendering-preview-lines">
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            </div>
          ) : (
            <div className="artifact-empty">
              Preview stays docked here when Vangogh starts rendering or when the artifact is ready.
            </div>
          )}
        </div>
      ) : (
        <div className="artifact-preview">
          <div className={`artifact-frame-wrapper artifact-frame-wrapper--${viewMode}`}>
            <iframe
              ref={iframeRef}
              className="artifact-iframe"
              title="Artifact preview"
              sandbox="allow-scripts allow-same-origin"
              srcDoc={html}
            />
          </div>
        </div>
      )}
    </section>
  );
}

function MessageBubble({
  role,
  text,
  agentName,
  createdAt,
  kind,
  meta,
  bullets,
}: ChatMessage): JSX.Element {
  const { thinking, body } = useMemo(() => splitThinkingBlock(text || ""), [text]);
  const renderedBody = useMemo(() => renderMarkdownHtml(body || ""), [body]);
  const toneClass = kind ? `message--${kind}` : "";
  const hasSystemCard = role === "event";

  return (
    <div className={`message message--${role} ${toneClass}`.trim()}>
      {role === "user" ? <div className="message-avatar">U</div> : null}
      {role === "assistant" ? <div className="message-avatar">{agentName?.[0]?.toUpperCase() || "A"}</div> : null}
      <div className={`message-bubble ${hasSystemCard ? "message-bubble--system-card" : ""}`}>
        {agentName ? <div className="message-sender message-sender--agent">{agentName}</div> : null}
        {thinking && role !== "user" ? (
          <div className="message-thinking" aria-label="Reasoning trace">
            <div className="message-thinking-title">Thinking</div>
            <pre className="message-thinking-body">{thinking}</pre>
          </div>
        ) : null}
        <div className="message-text message-markdown" dangerouslySetInnerHTML={{ __html: renderedBody || DOMPurify.sanitize(text || "") }} />
        {meta && Object.keys(meta).length > 0 ? (
          <div className="message-meta-row">
            {Object.entries(meta).map(([key, value]) => (
              <span className="message-meta-pill" key={`${createdAt}-${key}`}>
                <span className="message-meta-key">{key}</span>
                <span className="message-meta-value">{value}</span>
              </span>
            ))}
          </div>
        ) : null}
        {bullets && bullets.length > 0 ? (
          <div className="message-bullet-list">
            {bullets.map((item) => (
              <div key={`${createdAt}-${item}`} className="message-bullet-item">
                {item}
              </div>
            ))}
          </div>
        ) : null}
        <div className="message-time">
          {new Date(createdAt).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </div>
      </div>
    </div>
  );
}

function InlineRenderingCard(): JSX.Element | null {
  const { state } = useOrchestratorStore();
  const totalSections = state.artifact.totalSections ?? 0;
  const renderedSections = state.artifact.sections?.length ?? 0;
  const isActive = Boolean(state.artifact.loading) || totalSections > 0;

  if (!isActive) {
    return null;
  }

  const phase = phaseLabelFromState(
    state.artifact.loadingLabel || "",
    state.artifact.artifactKind || "",
    renderedSections,
    totalSections
  );
  const latestLabel = state.artifact.sections?.[state.artifact.sections.length - 1]?.label;
  const progress = totalSections > 0
    ? `${Math.min(renderedSections + (state.artifact.loading ? 1 : 0), totalSections)}/${totalSections}`
    : "Starting";

  return (
    <div className="message message--event message--rendering">
      <div className="message-bubble message-bubble--system-card message-bubble--rendering">
        <div className="message-sender message-sender--agent">Vangogh</div>
        <div className="message-rendering-head">
          <div>
            <div className="message-rendering-kicker">Rendering</div>
            <div className="message-rendering-title">Artifact generation is in progress</div>
          </div>
          <div className="message-rendering-progress">{progress}</div>
        </div>
        <div className="message-text">{phase}</div>
        {latestLabel ? <div className="message-rendering-latest">Latest section: {latestLabel}</div> : null}
      </div>
    </div>
  );
}

function ChatTranscript(): JSX.Element {
  const { state } = useOrchestratorStore();

  return (
    <div className="messages-list" id="messages">
      {state.messages.map((message) => (
        <MessageBubble key={message.id} {...message} />
      ))}
      <InlineRenderingCard />
    </div>
  );
}

function LiveWorkflowStatus(): JSX.Element {
  const { state } = useOrchestratorStore();
  const status = state.status?.status || (state.isSubmitting || state.isResuming ? "running" : "idle");
  const node = state.activeNode || state.status?.current_node || "orchestrator";

  return (
    <div className="live-status" role="status" aria-live="polite">
      <span className="live-status__label">System</span>
      <span className="live-status__item"><strong>Core</strong>{status}</span>
      <span className="live-status__item"><strong>Node</strong>{node}</span>
      <span className="live-status__item"><strong>Mode</strong>{state.workflowMode}</span>
      {state.threadId ? <span className="live-status__item"><strong>Thread</strong>{state.threadId.slice(0, 8)}</span> : null}
    </div>
  );
}

function HitlDropup(): JSX.Element | null {
  const { state, resume, dispatch } = useOrchestratorStore();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const firstInputRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    if (!state.hitl.open) {
      setAnswers({});
      return;
    }
    setAnswers(
      Object.fromEntries(state.hitl.questions.map((_, index) => [`q${index + 1}`, ""])) as Record<string, string>
    );
  }, [state.hitl.open, state.hitl.questions]);

  useEffect(() => {
    if (state.hitl.open) {
      window.setTimeout(() => firstInputRef.current?.focus(), 40);
    }
  }, [state.hitl.open]);

  if (!state.hitl.open) {
    return null;
  }

  return (
    <div className="hitl-dropup" aria-label="Clarification questions">
      <div className="hitl-dropup__header">
        <div>
          <div className="hitl-dropup__eyebrow">Clarification needed</div>
          <h3 className="hitl-dropup__title">BLAIQ needs a few structured answers</h3>
          <p className="hitl-dropup__subtitle">Answer inline to let Vangogh continue the rendering flow.</p>
        </div>
        <span className="hitl-dropup__badge">{state.hitl.agentNode}</span>
      </div>
      <div className="hitl-dropup__grid">
        {state.hitl.questions.map((question, index) => (
          <div key={`${question}-${index}`} className="hitl-dropup__card">
            <div className="hitl-dropup__question-index">Question {index + 1}</div>
            <div className="hitl-dropup__question">{question}</div>
            <textarea
              ref={index === 0 ? firstInputRef : undefined}
              className="hitl-dropup__input"
              placeholder="Add your answer..."
              value={answers[`q${index + 1}`] || ""}
              onChange={(event) =>
                setAnswers((current) => ({
                  ...current,
                  [`q${index + 1}`]: event.target.value,
                }))
              }
            />
            <div className="hitl-dropup__chips">
              {quickChips(question).map((chip) => (
                <button
                  key={chip}
                  type="button"
                  className="hitl-dropup__chip"
                  onClick={() =>
                    setAnswers((current) => ({
                      ...current,
                      [`q${index + 1}`]: chip,
                    }))
                  }
                >
                  {chip}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="hitl-dropup__actions">
        <button
          className="hitl-dropup__ghost"
          type="button"
          onClick={() => dispatch({ type: "set-hitl", payload: { open: false } })}
        >
          Close
        </button>
        <button
          className="hitl-dropup__submit"
          type="button"
          disabled={state.isResuming}
          onClick={() => {
            const payload = Object.fromEntries(
              Object.entries(answers).filter(([, value]) => value.trim().length > 0)
            ) as Record<string, string>;

            if (Object.keys(payload).length === 0) {
              return;
            }

            void resume({
              thread_id: state.hitl.threadId || state.threadId,
              agent_node: state.hitl.agentNode,
              answers: payload,
            });
          }}
        >
          {state.isResuming ? "Resuming…" : "Continue rendering"}
        </button>
      </div>
    </div>
  );
}

function ChatComposer(): JSX.Element {
  const { state, sendMessage, dispatch } = useOrchestratorStore();
  const [text, setText] = useState("");
  const [workflowMode, setWorkflowMode] = useState(state.workflowMode);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const inputDisabled = state.hitl.open || state.isSubmitting || state.isResuming || state.isRegenerating;

  useEffect(() => {
    setWorkflowMode(state.workflowMode);
  }, [state.workflowMode]);

  function resize(): void {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }

  async function submit(event?: FormEvent): Promise<void> {
    event?.preventDefault();
    const value = text.trim();
    if (!value || inputDisabled) return;
    setText("");
    try {
      await sendMessage(value);
    } finally {
      setTimeout(resize, 0);
    }
  }

  return (
    <form className="input-wrapper" onSubmit={submit}>
      <HitlDropup />
      <div className="input-row">
        <textarea
          ref={textareaRef}
          className="input-textarea"
          placeholder={state.hitl.open ? "Answer the clarifications above to continue." : "Ask BLAIQ to create, analyze, or synthesize."}
          rows={1}
          value={text}
          disabled={inputDisabled}
          onChange={(event) => {
            setText(event.target.value);
            resize();
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void submit();
            }
          }}
          aria-label="Message input"
        />
        <div className="input-mode-switcher" aria-label="Workflow mode">
          <select
            value={workflowMode}
            onChange={(event) => {
              const value = event.target.value as typeof workflowMode;
              setWorkflowMode(value);
              dispatch({ type: "set-workflow-mode", workflowMode: value });
            }}
          >
            <option value="standard">Standard</option>
            <option value="deep_research">Deep research</option>
            <option value="creative">Creative</option>
          </select>
        </div>
        <button
          className="input-send"
          type="submit"
          aria-label="Send message"
          disabled={!text.trim() || inputDisabled}
        >
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
            <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" fill="white" />
          </svg>
        </button>
      </div>
      <div className="input-footnote">
        <span>Chat-first workflow</span>
        <span>Preview appears only when Vangogh is active</span>
      </div>
    </form>
  );
}

function SchemaPanel(): JSX.Element {
  const { state, regenerate } = useOrchestratorStore();
  const [draft, setDraft] = useState<ContentSchema | null>(state.schema.draft);

  useEffect(() => {
    setDraft(state.schema.draft);
  }, [state.schema.draft]);

  if (!draft) {
    return (
      <section className="rail-panel schema-panel">
        <div className="rail-panel__header">
          <div>
            <div className="rail-panel__eyebrow">Schema</div>
            <h3 className="rail-panel__title">Editable structure</h3>
          </div>
        </div>
        <div className="rail-empty">Schema becomes editable here once Vangogh returns a draft.</div>
      </section>
    );
  }

  return (
    <section className="rail-panel schema-panel" aria-label="Content schema editor">
      <div className="rail-panel__header">
        <div>
          <div className="rail-panel__eyebrow">Schema</div>
          <h3 className="rail-panel__title">Refine the structure</h3>
        </div>
      </div>
      <div className="schema-fields">
        <div className="schema-field">
          <label className="schema-field-label">Vision Statement</label>
          <textarea
            className="schema-field-input"
            rows={2}
            value={draft.vision_statement}
            onChange={(event) =>
              setDraft((current) => (current ? { ...current, vision_statement: event.target.value } : current))
            }
          />
        </div>
        <div className="schema-field">
          <label className="schema-field-label">Target Audience</label>
          <textarea
            className="schema-field-input"
            rows={2}
            value={draft.target_audience}
            onChange={(event) =>
              setDraft((current) => (current ? { ...current, target_audience: event.target.value } : current))
            }
          />
        </div>
        <div className="schema-field">
          <label className="schema-field-label">KPIs</label>
          <textarea
            className="schema-field-input"
            rows={3}
            value={listToMultiline(draft.kpis)}
            onChange={(event) =>
              setDraft((current) => (current ? { ...current, kpis: parseMultilineList(event.target.value) } : current))
            }
          />
        </div>
        <div className="schema-field">
          <label className="schema-field-label">Strategic Pillars</label>
          <textarea
            className="schema-field-input"
            rows={4}
            value={listToMultiline(draft.strategic_pillars)}
            onChange={(event) =>
              setDraft((current) =>
                current ? { ...current, strategic_pillars: parseMultilineList(event.target.value) } : current
              )
            }
          />
        </div>
        <div className="schema-field">
          <label className="schema-field-label">Timeline</label>
          <textarea
            className="schema-field-input"
            rows={2}
            value={draft.timeline}
            onChange={(event) =>
              setDraft((current) => (current ? { ...current, timeline: event.target.value } : current))
            }
          />
        </div>
      </div>
      <button
        className="schema-regenerate"
        type="button"
        disabled={!state.threadId || state.isRegenerating}
        onClick={() => {
          if (!draft || !state.threadId) {
            return;
          }
          void regenerate({
            thread_id: state.threadId,
            patched_schema: draft,
            workflow_mode: state.workflowMode,
          });
        }}
      >
        {state.isRegenerating ? "Refreshing…" : "Regenerate from schema edits"}
      </button>
    </section>
  );
}

function ContextRail({
  open,
  initialTab = "plan",
}: {
  open: boolean;
  initialTab?: RailTab;
}): JSX.Element | null {
  const { state } = useOrchestratorStore();
  const [activeTab, setActiveTab] = useState<RailTab>(initialTab);

  useEffect(() => {
    if (state.artifact.loading || state.artifact.totalSections || (state.artifact.visible && state.artifact.html)) {
      setActiveTab("preview");
      return;
    }
    if (state.governance.report) {
      setActiveTab("governance");
      return;
    }
    if (state.schema.draft) {
      setActiveTab("schema");
    }
  }, [
    state.artifact.html,
    state.artifact.loading,
    state.artifact.totalSections,
    state.artifact.visible,
    state.governance.report,
    state.schema.draft,
  ]);

  if (!open) {
    return null;
  }

  const tabs: { id: RailTab; label: string }[] = [
    { id: "preview", label: "Preview" },
    { id: "plan", label: "Plan" },
    { id: "schema", label: "Schema" },
    { id: "governance", label: "Governance" },
  ];

  return (
    <aside className={`workspace__rail ${open ? "workspace__rail--open" : ""}`} aria-label="Context rail">
      <div className="workspace__rail-tabs">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`workspace__rail-tab ${activeTab === tab.id ? "workspace__rail-tab--active" : ""}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div className="workspace__rail-body">
        {activeTab === "preview" ? <ArtifactPreview /> : null}
        {activeTab === "plan" ? <TimelineView /> : null}
        {activeTab === "schema" ? <SchemaPanel /> : null}
        {activeTab === "governance" ? <GovernancePanel /> : null}
      </div>
    </aside>
  );
}

const SUGGESTION_CHIPS = [
  "Create a pitch deck from our last 12 months of sales",
  "Summarize the strongest proof points in our docs",
  "Turn our strategy notes into an executive briefing",
  "Design a landing page narrative from uploaded materials",
];

function WelcomeState(): JSX.Element {
  const { sendMessage } = useOrchestratorStore();
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  function resize(): void {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }

  async function submit(event?: FormEvent): Promise<void> {
    event?.preventDefault();
    const value = text.trim();
    if (!value) return;
    setText("");
    try {
      await sendMessage(value);
    } finally {
      setTimeout(resize, 0);
    }
  }

  function handleChip(chip: string): void {
    setText(chip);
    textareaRef.current?.focus();
  }

  return (
    <div className="workspace__focus">
      <div className="workspace__focus-hero">
        <div className="workspace__focus-kicker">BLAIQ Workspace</div>
        <h1 className="workspace__focus-title">One conversation. One live system behind it.</h1>
        <p className="workspace__focus-copy">
          Start in chat. Core will route the request, GraphRAG will assemble evidence, Vangogh will render when needed, and the preview rail will open only when there is something worth showing.
        </p>
      </div>
      <form className="workspace__focus-form" onSubmit={submit}>
        <div className="input-row input-row--focus">
          <textarea
            ref={textareaRef}
            className="input-textarea"
            placeholder="Create me a pitch deck based on my sales in the last 1 year"
            rows={1}
            value={text}
            onChange={(event) => {
              setText(event.target.value);
              resize();
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void submit();
              }
            }}
            aria-label="Workflow description"
          />
          <button className="input-send" type="submit" aria-label="Send" disabled={!text.trim()}>
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" fill="white" />
            </svg>
          </button>
        </div>
      </form>
      <div className="workspace__focus-chips">
        {SUGGESTION_CHIPS.map((chip) => (
          <button key={chip} className="input-chip" type="button" onClick={() => handleChip(chip)}>
            {chip}
          </button>
        ))}
      </div>
    </div>
  );
}

function ActiveState(): JSX.Element {
  const { state } = useOrchestratorStore();
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const stickToBottomRef = useRef(true);
  const shouldShowRail =
    Boolean(state.artifact.loading) ||
    Boolean(state.artifact.totalSections && state.artifact.totalSections > 0) ||
    Boolean(state.artifact.visible && state.artifact.html) ||
    Boolean(state.schema.draft) ||
    Boolean(state.governance.report) ||
    Boolean(state.routing.executionPlan.length);

  useEffect(() => {
    const el = chatScrollRef.current;
    if (!el) return;

    const updateStickiness = (): void => {
      const remaining = el.scrollHeight - el.scrollTop - el.clientHeight;
      stickToBottomRef.current = remaining < 96;
    };

    updateStickiness();
    el.addEventListener("scroll", updateStickiness, { passive: true });
    return () => el.removeEventListener("scroll", updateStickiness);
  }, []);

  useLayoutEffect(() => {
    const el = chatScrollRef.current;
    if (!el || !stickToBottomRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [
    state.messages.length,
    state.artifact.loading,
    state.artifact.loadingLabel,
    state.artifact.sections?.length,
    state.hitl.open,
    state.isResuming,
    state.lastError,
  ]);

  return (
    <div className="workspace__active">
      <div className="workspace__chat">
        <LiveWorkflowStatus />
        <div className="chat-container" ref={chatScrollRef}>
          <ChatTranscript />
        </div>
        <div className="input-container">
          <ChatComposer />
        </div>
      </div>
      <ContextRail open={shouldShowRail} initialTab="plan" />
    </div>
  );
}

export function OrchestratorWorkspace(): JSX.Element {
  const { state, refreshStatus } = useOrchestratorStore();

  useEffect(() => {
    if (!state.threadId) return;
    void refreshStatus(state.threadId).catch(() => {
      // ignore initial hydration failures
    });
  }, [refreshStatus, state.threadId]);

  const hasMessages = state.messages.length > 0;

  return <div className="workspace">{hasMessages ? <ActiveState /> : <WelcomeState />}</div>;
}

export function RunDetailView(): JSX.Element {
  const { state, refreshStatus, refreshWorkflows } = useOrchestratorStore();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const threadId = params.get("thread_id") || params.get("threadId") || state.threadId;
    if (threadId) {
      void refreshStatus(threadId).catch(() => {
        // ignore
      });
    }
    void refreshWorkflows().catch(() => {
      // ignore
    });
  }, [refreshStatus, refreshWorkflows, state.threadId]);

  const status = state.status;
  const finalArtifact = status?.final_artifact;

  return (
    <div className="workspace">
      <section className="run-detail-grid">
        <div className="run-detail-card">
          <div className="run-detail-title">Workflow Status</div>
          <div className="run-detail-row">
            <span>Status</span>
            <strong>{status?.status || "unknown"}</strong>
          </div>
          <div className="run-detail-row">
            <span>Current node</span>
            <strong>{status?.current_node || state.activeNode || "idle"}</strong>
          </div>
          <div className="run-detail-row">
            <span>Updated</span>
            <strong>{status?.updated_at || "—"}</strong>
          </div>
          {status?.error_message ? <div className="run-detail-error">{status.error_message}</div> : null}
        </div>
        <div className="run-detail-card">
          <div className="run-detail-title">Final Artifact</div>
          {finalArtifact ? (
            <div className="run-detail-json">
              <pre>{JSON.stringify(finalArtifact, null, 2)}</pre>
            </div>
          ) : (
            <div className="run-detail-empty">No artifact available yet.</div>
          )}
        </div>
      </section>
      <div className="workspace__active">
        <div className="workspace__chat">
          <LiveWorkflowStatus />
          <div className="chat-container">
            <ChatTranscript />
          </div>
        </div>
        <ContextRail open={true} initialTab="plan" />
      </div>
    </div>
  );
}

export function ArtifactDetailView(): JSX.Element {
  const { state, refreshStatus, openArtifact } = useOrchestratorStore();

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const threadId = params.get("thread_id") || params.get("threadId") || state.threadId;
    const html = params.get("html") || params.get("artifact_html");
    if (html) {
      openArtifact(html, "Artifact preview", "status");
    } else if (threadId) {
      void refreshStatus(threadId).catch(() => {
        // ignore
      });
    }
  }, [openArtifact, refreshStatus, state.threadId]);

  return (
    <div className="workspace">
      <div className="workspace__active">
        <div className="workspace__chat">
          <div className="chat-container">
            <ChatTranscript />
          </div>
        </div>
        <ContextRail open={true} initialTab="preview" />
      </div>
    </div>
  );
}
