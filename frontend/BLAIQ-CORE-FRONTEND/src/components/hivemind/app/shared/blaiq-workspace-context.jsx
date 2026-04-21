import React, { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { getWorkflowStatus, resumeWorkflow, submitWorkflow } from './blaiq-client';

const BlaiqWorkspaceContext = createContext(null);
const WORKSPACE_STORAGE_KEY = 'blaiq.workspace.v1';

const promptSuggestions = [
  'Create a pitch deck from our last 12 months of sales',
  'Turn our strategy notes into an executive briefing',
  'Build a landing page narrative from uploaded materials',
];

function eventType(event) {
  return event.normalized_type || event.type;
}

function extractArtifactHtml(event) {
  return (
    event?.final_artifact?.governance_report?.approved_output ||
    event?.final_artifact?.html_artifact ||
    event?.content_draft?.html_artifact ||
    ''
  );
}

/** Extract a plain-text response for retrieval-only workflows (no content agent). */
function extractTextResponse(event) {
  return (
    event?.response ||
    event?.answer ||
    event?.text ||
    event?.final_artifact?.text ||
    event?.final_artifact?.response ||
    event?.final_artifact?.answer ||
    event?.content_draft?.text ||
    event?.content_draft?.response ||
    event?.content ||
    ''
  );
}

/** True when the routing used a content / rendering agent. */
function isContentWorkflow(routingDecision) {
  if (!routingDecision) return true; // assume content until we know better
  const agents = [
    routingDecision.primary_agent,
    ...(routingDecision.helper_agents || []),
    ...(routingDecision.selected_agents || []),
  ]
    .filter(Boolean)
    .map((a) => String(a).toLowerCase());
  return agents.some(
    (a) => a.includes('content') || a.includes('vangogh') || a.includes('echo')
  );
}

function extractSchema(event) {
  return event?.final_artifact?.schema_data || event?.content_draft?.schema_data || null;
}

function extractPreviewFragment(event) {
  const sections = event?.content_draft?.artifact_manifest?.sections;
  const sectionFragments = Array.isArray(sections)
    ? sections.map((section) => section?.html_fragment).filter(Boolean).join('\n')
    : '';
  return (
    event?.artifact_preview?.html_fragment ||
    event?.html_fragment ||
    event?.content_draft?.html_fragment ||
    sectionFragments ||
    ''
  );
}

export function buildWorkflowPlanFromRouting(event = {}) {
  const selectedAgents = [
    event.primary_agent,
    ...(event.helper_agents || []),
    ...(event.selected_agents || []),
  ]
    .filter(Boolean)
    .map((agent) => String(agent));
  const lowerAgents = selectedAgents.map((agent) => agent.toLowerCase());
  const hasGraph = lowerAgents.some((agent) => agent.includes('graph') || agent.includes('rag') || agent.includes('retriev'));
  const hasContent = lowerAgents.some((agent) => agent.includes('content') || agent.includes('vangogh') || agent.includes('poster') || agent.includes('deck'));

  const stages = [
    { id: 'routing', label: 'Routing', agent: 'Strategist', state: 'active', detail: 'CORE is selecting the route.' },
  ];
  if (hasGraph || Array.isArray(event.execution_plan) && event.execution_plan.includes('graphrag')) {
    stages.push({ id: 'evidence', label: 'Evidence', agent: 'GraphRAG', state: 'pending', detail: 'Retrieval and source grounding.' });
  }
  if (hasContent || Array.isArray(event.execution_plan) && event.execution_plan.includes('content')) {
    stages.push({ id: 'content_director', label: 'Content Director', agent: 'Core + Content', state: 'pending', detail: 'Blueprinting page-level structure.' });
    stages.push({ id: 'hitl', label: 'Human Review', agent: 'User + Core', state: 'pending', detail: 'Clarification or page review gate.' });
    stages.push({ id: 'rendering', label: 'Rendering', agent: 'Vangogh', state: 'pending', detail: 'Blueprint-backed section rendering.' });
  }
  stages.push({ id: 'governance', label: 'Governance', agent: 'Governance', state: 'pending', detail: 'Policy and quality checks.' });
  stages.push({ id: 'delivery', label: 'Delivery', agent: 'Core', state: 'pending', detail: 'Terminal completion and handoff.' });

  return {
    schemaVersion: 'workflow_plan.v1',
    routeMode: String(event.route_mode || event.strategy?.route_mode || ''),
    primaryAgent: String(event.primary_agent || ''),
    helperAgents: (event.helper_agents || []).filter(Boolean).map((agent) => String(agent)),
    selectedAgents,
    currentStageId: 'routing',
    currentStatus: 'running',
    workflowComplete: false,
    hitlMode: '',
    hitlNode: '',
    contentDirectorPlan: null,
    progressPct: 0,
    stages,
    liveAgents: (event.live_agents || []).filter(Boolean).map((agent) => String(agent?.name || agent)),
  };
}

export function recalcWorkflowPlan(plan, patch = {}) {
  const base = plan || buildWorkflowPlanFromRouting({});
  const next = {
    ...base,
    ...patch,
    stages: Array.isArray(base.stages) ? base.stages.map((stage) => ({ ...stage })) : [],
  };
  const order = ['routing', 'evidence', 'content_director', 'hitl', 'rendering', 'governance', 'delivery'];
  const currentIndex = Math.max(0, order.indexOf(next.currentStageId || 'routing'));
  next.stages = next.stages.map((stage) => {
    const idx = order.indexOf(stage.id);
    if (next.workflowComplete) {
      return { ...stage, state: 'done' };
    }
    if (idx < currentIndex) {
      return { ...stage, state: 'done' };
    }
    if (idx === currentIndex) {
      return { ...stage, state: next.currentStatus === 'blocked_on_user' ? 'blocked' : 'active' };
    }
    return { ...stage, state: 'pending' };
  });
  const doneCount = next.stages.filter((stage) => stage.state === 'done').length;
  next.progressPct = next.workflowComplete ? 100 : Math.round((doneCount / Math.max(1, next.stages.length)) * 100);
  return next;
}

function buildLoadingPreviewHtml({ artifactKind = 'content', label = 'Rendering', current = 0, total = 0 } = {}) {
  const progress = total > 0 ? `${Math.min(Math.max(current, 0), total)} / ${total}` : '';
  const safeLabel = String(label || '').slice(0, 120);
  const width = total > 0 ? Math.max(4, Math.min(100, Math.round((Math.max(current, 0) / total) * 100))) : 18;
  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600;700&family=Manrope:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
      :root { --paper:#F6F4F1; --stone:#E4DED2; --coral:#FF5C4B; --black:#0B0B0B; }
      html, body { margin:0; min-height:100%; background: var(--stone); color: var(--black); font-family:'Manrope', system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }
      .shell { min-height:100vh; display:grid; grid-template-rows:auto 1fr; }
      .top { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:16px 18px; background: rgba(246,244,241,0.92); border-bottom:1px solid rgba(0,0,0,0.08); }
      .kicker { font-size:11px; text-transform:uppercase; letter-spacing:0.18em; color: rgba(0,0,0,0.52); }
      .title { margin-top:3px; font-family:'Cormorant Garamond', serif; font-size:20px; font-weight:600; letter-spacing:-0.02em; }
      .badge { display:inline-flex; align-items:center; gap:10px; padding:8px 12px; border-radius:999px; background: rgba(255,92,75,0.12); border:1px solid rgba(255,92,75,0.25); color: rgba(0,0,0,0.78); font-size:11px; font-weight:700; letter-spacing:0.12em; text-transform:uppercase; white-space:nowrap; }
      .dot { width:8px; height:8px; border-radius:999px; background: var(--coral); box-shadow: 0 0 0 6px rgba(255,92,75,0.12); animation: pulse 1.2s ease-in-out infinite; }
      .body { display:grid; place-items:center; padding:22px 18px 26px; }
      .card { width:min(920px, 100%); border-radius:26px; background: rgba(246,244,241,0.9); border:1px solid rgba(0,0,0,0.08); box-shadow: 0 24px 80px rgba(0,0,0,0.10); overflow:hidden; }
      .inner { padding:22px 20px 24px; }
      .line1 { font-size:14px; font-weight:650; letter-spacing:-0.01em; }
      .line2 { margin-top:10px; color: rgba(0,0,0,0.58); font-size:13px; line-height:1.75; }
      .barWrap { margin-top:16px; height:10px; border-radius:999px; background: rgba(0,0,0,0.08); overflow:hidden; }
      .bar { height:100%; width:${width}%; background: linear-gradient(90deg, rgba(255,92,75,0.88), rgba(255,92,75,0.55)); border-radius:999px; }
      @keyframes pulse { 0%,100%{transform:scale(1);opacity:1} 50%{transform:scale(0.92);opacity:0.65} }
    </style>
  </head>
  <body>
    <div class="shell">
      <header class="top">
        <div>
          <div class="kicker">Live preview</div>
          <div class="title">${safeLabel || 'Rendering artifact'}</div>
        </div>
        <div class="badge"><span class="dot"></span>${String(artifactKind || 'content')}${progress ? ` · ${progress}` : ''}</div>
      </header>
      <main class="body">
        <article class="card">
          <div class="inner">
            <div class="line1">Generating sections from templates and Brand DNA.</div>
            <div class="line2">This preview updates as each section is produced.</div>
            <div class="barWrap"><div class="bar"></div></div>
          </div>
        </article>
      </main>
    </div>
  </body>
</html>`;
}

function buildSectionPreviewHtml({ artifactKind = 'content', sectionLabel = '', sectionIndex = 0, totalSections = 0, htmlFragment = '' } = {}) {
  const shell = buildLoadingPreviewHtml({
    artifactKind,
    label: sectionLabel || 'Section ready',
    current: sectionIndex + 1,
    total: totalSections,
  });
  const fragment = String(htmlFragment || '').trim();
  if (!fragment) return shell;
  return shell.replace(
    /<article class="card">[\s\S]*?<\/article>/,
    `<article class="card"><div style="min-height: 72vh; background: #F6F4F1;">
      <script src="https://unpkg.com/@tailwindcss/browser@4"></script>
      <div id="vangogh-fragment-root">${fragment}</div>
    </div></article>`
  );
}

function buildPreviewHtmlFromFragments(fragments, meta = {}) {
  const list = Array.isArray(fragments) ? fragments : [];
  const last = list.length ? list[list.length - 1] : null;
  if (!last || !last.html) return '';
  return buildSectionPreviewHtml({
    artifactKind: meta.artifactKind || 'content',
    sectionLabel: last.label || meta.label || '',
    sectionIndex: Number.isFinite(last.index) ? last.index : (meta.sectionIndex || 0),
    totalSections: meta.totalSections || 0,
    htmlFragment: last.html,
  });
}

function formatEventSummary(event) {
  const type = eventType(event);
  switch (type) {
    case 'routing_decision':
      return {
        title: 'Core routed the request',
        body: 'Strategist selected the workflow path and active agents.',
      };
    case 'evidence_summary':
    case 'evidence_ready':
      return {
        title: 'GraphRAG assembled evidence',
        body: 'Relevant source material is ready for synthesis.',
      };
    case 'evidence_refreshed':
      return {
        title: 'GraphRAG refreshed the evidence',
        body: 'Clarifications were merged into the working context.',
      };
    case 'hitl_required':
      return {
        title: 'Clarification needed',
        body: 'Answer the inline questions to continue rendering.',
      };
    case 'rendering_started':
    case 'artifact_type_resolved':
      return {
        title: 'Vangogh started rendering',
        body: 'The artifact is being composed section by section.',
      };
    case 'artifact_ready':
    case 'artifact_composed':
    case 'content_ready':
      // Handled dynamically in handleEvent — this is the fallback
      return {
        title: 'Response ready',
        body: 'The workflow has completed processing.',
      };
    case 'governance':
      return {
        title: 'Governance evaluated the result',
        body: event.governance_report?.validation_passed ? 'Checks passed.' : 'Review the flagged items.',
      };
    default:
      return {
        title: type.replace(/_/g, ' '),
        body: event.message || 'Workflow update received.',
      };
  }
}

export function normalizePreviewHtml(rawHtml) {
  let html = String(rawHtml || '').trim();
  if (!html) {
    return '<!doctype html><html><body style="margin:0;background:#f8f5ef;color:#111827;font-family:Inter,system-ui;display:grid;place-items:center;height:100vh;"><div>Preview will appear here</div></body></html>';
  }

  html = html
    .replace(/^```html\s*/i, '')
    .replace(/^```[\w-]*\s*/i, '')
    .replace(/\s*```$/, '')
    .trim();

  if (
    html.startsWith('&lt;') ||
    html.includes('&lt;div') ||
    html.includes('&lt;section') ||
    html.includes('&lt;!DOCTYPE')
  ) {
    html = html
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&amp;/g, '&');
  }

  if ((html.startsWith('"') && html.endsWith('"')) || (html.startsWith("'") && html.endsWith("'"))) {
    html = html.slice(1, -1).trim();
  }

  const containsHtmlTag = /<([a-z][\w-]*)(?:\s|>)/i.test(html);
  if (!containsHtmlTag) {
    const escaped = html
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
    return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600;700&family=Manrope:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
      :root {
        --paper: #F6F4F1;
        --stone: #E4DED2;
        --coral: #FF5C4B;
        --black: #0B0B0B;
      }
      html, body {
        margin: 0;
        min-height: 100%;
        background: radial-gradient(circle at top left, rgba(255,92,75,0.08), transparent 26%), var(--paper);
        color: var(--black);
        font-family: 'Manrope', Inter, system-ui, sans-serif;
      }
      .preview-shell {
        min-height: 100vh;
        display: grid;
        place-items: center;
        padding: 40px 20px;
      }
      .preview-card {
        width: min(920px, 100%);
        background: rgba(255,255,255,0.8);
        border: 1px solid rgba(0,0,0,0.08);
        border-radius: 28px;
        box-shadow: 0 24px 80px rgba(0,0,0,0.08);
        overflow: hidden;
      }
      .preview-head {
        display: flex;
        justify-content: space-between;
        gap: 16px;
        padding: 18px 22px;
        background: rgba(228,222,210,0.55);
        border-bottom: 1px solid rgba(0,0,0,0.06);
      }
      .preview-kicker {
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.18em;
        color: rgba(0,0,0,0.48);
      }
      .preview-title {
        margin-top: 4px;
        font-family: 'Cormorant Garamond', serif;
        font-size: 28px;
        font-weight: 600;
      }
      .preview-body {
        padding: 28px 22px 32px;
        white-space: pre-wrap;
        line-height: 1.8;
        font-size: 15px;
      }
      .preview-badge {
        align-self: flex-start;
        padding: 8px 12px;
        border-radius: 999px;
        background: var(--coral);
        color: white;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
    </style>
  </head>
  <body>
    <div class="preview-shell">
      <article class="preview-card">
        <header class="preview-head">
          <div>
            <div class="preview-kicker">Artifact Preview</div>
            <div class="preview-title">Rendered Response</div>
          </div>
          <div class="preview-badge">Text fallback</div>
        </header>
        <div class="preview-body">${escaped}</div>
      </article>
    </div>
  </body>
</html>`;
  }

  const hasDocumentShell = /<(?:!doctype|html|head|body)\b/i.test(html);
  if (hasDocumentShell) {
    return html;
  }

  return `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <script src="https://unpkg.com/@tailwindcss/browser@4"></script>
    <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@400;500;600;700&family=Manrope:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
      :root {
        --paper: #F6F4F1;
        --stone: #E4DED2;
        --coral: #FF5C4B;
        --black: #000000;
      }
      html, body {
        margin: 0;
        min-height: 100%;
        background: var(--paper);
        color: var(--black);
        font-family: 'Manrope', Inter, system-ui, sans-serif;
        -webkit-font-smoothing: antialiased;
      }
      h1, h2, h3, h4, h5, h6 {
        font-family: 'Cormorant Garamond', serif;
      }
    </style>
  </head>
  <body>
    ${html}
  </body>
</html>`;
}

export function quickChips(question) {
  const lower = question.toLowerCase();
  if (lower.includes('audience') || lower.includes('target')) return ['Board', 'Investors', 'Enterprise buyers'];
  if (lower.includes('metric') || lower.includes('revenue') || lower.includes('kpi')) return ['Revenue growth', 'Pipeline', 'Gross margin'];
  if (lower.includes('style') || lower.includes('visual') || lower.includes('design')) return ['Minimal', 'Executive', 'Analytical'];
  return ['Use best judgement', 'Keep it concise', 'Show strongest proof'];
}

export function BlaiqWorkspaceProvider({ children }) {
  const [isDayMode, setIsDayMode] = useState(() => {
    try { return window.localStorage.getItem('blaiq.theme') === 'day'; } catch { return true; }
  });

  function toggleDayMode() {
    setIsDayMode((prev) => {
      const next = !prev;
      try { window.localStorage.setItem('blaiq.theme', next ? 'day' : 'night'); } catch {}
      return next;
    });
  }

  const [messages, setMessages] = useState([]);
  const [query, setQuery] = useState('');
  const [activeTab, setActiveTab] = useState('plan');
  const [workflowMode, setWorkflowMode] = useState('standard');
  const [threadId, setThreadId] = useState('');
  const [timeline, setTimeline] = useState([]);
  const [previewHtml, setPreviewHtml] = useState('');
  const [previewFragments, setPreviewFragments] = useState([]);
  const [schema, setSchema] = useState(null);
  const [governance, setGovernance] = useState(null);
  const [hitl, setHitl] = useState({ open: false, questions: [], answers: {}, agentNode: 'content_node' });
  const [renderState, setRenderState] = useState({ loading: false, label: '', section: 0, total: 0, artifactKind: '' });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isResuming, setIsResuming] = useState(false);
  const [lastEventType, setLastEventType] = useState('');
  const [activeAgents, setActiveAgents] = useState([]);
  const [liveAgents, setLiveAgents] = useState([]);
  const [routingDecision, setRoutingDecision] = useState(null);
  const [evidenceSummary, setEvidenceSummary] = useState(null);
  const [hasConversation, setHasConversation] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  const [thinkingLabel, setThinkingLabel] = useState('');
  const [workflowPlan, setWorkflowPlan] = useState(null);
  const [workflowComplete, setWorkflowComplete] = useState(false);
  const sessionIdRef = useRef('');
  const roomNumberRef = useRef('');

  const rightRailOpen = useMemo(
    () => Boolean(previewHtml || previewFragments.length || renderState.loading || schema || governance || timeline.length || workflowPlan),
    [previewHtml, previewFragments.length, renderState.loading, schema, governance, timeline.length, workflowPlan]
  );

  function generateId() {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID();
    }
    // Fallback for non-secure contexts (HTTP on LAN)
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  function ensureBrowserSession() {
    if (!sessionIdRef.current) sessionIdRef.current = generateId();
    if (!roomNumberRef.current) roomNumberRef.current = `room-${sessionIdRef.current}`;
  }

  function buildChatHistory(sourceMessages = messages) {
    return sourceMessages
      .filter((item) => ['user', 'assistant', 'system'].includes(item.role) && item.content)
      .slice(-20)
      .map((item) => ({
        role: item.role === 'system' ? 'assistant' : item.role,
        content: String(item.content),
      }));
  }

  function pushSystemEvent(event) {
    const summary = formatEventSummary(event);
    setMessages((current) => [
      ...current,
      {
        id: `${Date.now()}-${Math.random()}`,
        role: 'system',
        title: summary.title,
        content: summary.body,
      },
    ]);
  }

  function pushTimeline(label, state = 'active') {
    setTimeline((current) => {
      const existing = current.find((item) => item.label === label);
      if (existing) {
        return current.map((item) => item.label === label ? { ...item, state, at: new Date().toLocaleTimeString() } : item);
      }
      return [...current, { label, state, at: new Date().toLocaleTimeString() }];
    });
  }

  function addLiveAgents(agents = []) {
    const incoming = agents
      .filter(Boolean)
      .map((agent) => String(agent).trim())
      .filter(Boolean);
    if (!incoming.length) return;
    setLiveAgents((current) => {
      const merged = [...current];
      incoming.forEach((agent) => {
        if (!merged.some((existing) => String(existing).toLowerCase() === String(agent).toLowerCase())) {
          merged.push(agent);
        }
      });
      return merged;
    });
  }

  function handleEvent(event) {
    const type = eventType(event);
    setLastEventType(type);
    if (event.thread_id) setThreadId(event.thread_id);

    if (type === 'routing_decision') {
      const agents = [
        event.primary_agent,
        ...(event.helper_agents || []),
      ].filter(Boolean);
      setActiveAgents(agents);
      addLiveAgents(['strategist', ...agents]);
      setRoutingDecision(event);
      setWorkflowPlan(recalcWorkflowPlan(buildWorkflowPlanFromRouting(event), {
        currentStageId: Array.isArray(event.execution_plan) && event.execution_plan.includes('graphrag') ? 'evidence' : 'content_director',
        currentStatus: 'running',
        workflowComplete: false,
      }));
      pushTimeline('Routing', 'done');
      // Update thinking label — don't push a system message
      setThinkingLabel('Routing to ' + agents.map((a) => String(a).split('-').pop() || a).join(', '));
    }

    if (type === 'evidence_summary' || type === 'evidence_ready' || type === 'evidence_refreshed') {
      setEvidenceSummary(event);
      addLiveAgents(['graphrag']);
      setWorkflowPlan((current) => recalcWorkflowPlan(current, {
        currentStageId: current?.stages?.some((stage) => stage.id === 'content_director' || stage.id === 'rendering')
          ? 'content_director'
          : 'governance',
        currentStatus: 'running',
      }));
      pushTimeline('Evidence', 'done');
      // Update thinking label — don't push a system message
      setThinkingLabel('Gathering evidence from knowledge base');
    }

    if (type === 'content_director_plan') {
      setWorkflowPlan((current) => recalcWorkflowPlan(current, {
        contentDirectorPlan: event.plan || event.content_director_plan || event.workflow_plan || event,
        currentStageId: 'rendering',
        currentStatus: 'running',
      }));
    }

    if (type === 'rendering_started' || type === 'artifact_type_resolved') {
      setActiveTab('preview');
      setPreviewFragments([]);
      const planPatch = {
        currentStageId: 'rendering',
        currentStatus: 'running',
      };
      if (type === 'artifact_type_resolved' && event.section_ids) {
        planPatch.contentDirectorPlan = {
          ...(workflowPlan?.contentDirectorPlan || {}),
          pages: event.section_ids.map((sectionId, index) => ({
            page_number: index + 1,
            section_id: sectionId,
          })),
        };
      }
      setWorkflowPlan((current) => recalcWorkflowPlan(current, planPatch));
      setRenderState({
        loading: true,
        label: event.message || 'Rendering artifact',
        section: 0,
        total: Number(event.total_sections || 0),
        artifactKind: String(event.kind || event.artifact_kind || ''),
      });
      addLiveAgents(['vangogh']);
      pushTimeline('Rendering', 'active');
      setThinkingLabel('Rendering artifact');
      setPreviewHtml(buildLoadingPreviewHtml({
        artifactKind: String(event.kind || event.artifact_kind || 'content'),
        label: event.message || 'Rendering artifact',
        current: 0,
        total: Number(event.total_sections || 0),
      }));
    }

    if (type === 'section_started') {
      setWorkflowPlan((current) => recalcWorkflowPlan(current, {
        currentStageId: 'rendering',
        currentStatus: 'running',
      }));
      setRenderState((current) => ({
        ...current,
        loading: true,
        label: String(event.section_label || event.message || 'Rendering section'),
        section: Number(event.section_index || 0) + 1,
        total: current.total || Number(event.total_sections || 0),
      }));
    }

    if (type === 'section_ready') {
      const fragment = extractPreviewFragment(event);
      if (fragment) {
        setPreviewFragments((current) => {
          const idx = Number(event.section_index || 0);
          const next = current.filter((item) => item && item.index !== idx);
          next.push({ index: idx, label: String(event.section_label || ''), html: String(fragment) });
          next.sort((a, b) => (a.index ?? 0) - (b.index ?? 0));
          setPreviewHtml(buildPreviewHtmlFromFragments(next, {
            artifactKind: String(renderState.artifactKind || event.kind || event.artifact_kind || 'content'),
            totalSections: Number(renderState.total || event.total_sections || 0),
          }));
          return next;
        });
      }
      setWorkflowPlan((current) => recalcWorkflowPlan(current, {
        currentStageId: 'rendering',
        currentStatus: 'running',
      }));
      setRenderState((current) => ({
        ...current,
        loading: true,
        label: String(event.section_label || current.label),
        section: Number(event.section_index || 0) + 1,
      }));
    }

    if (type === 'artifact_ready' || type === 'artifact_composed' || type === 'content_ready' || type === 'complete') {
      const html = extractArtifactHtml(event);
      const textResponse = extractTextResponse(event);
      const contentFlow = isContentWorkflow(routingDecision);

      // Stop thinking — final response is here
      setIsThinking(false);
      setThinkingLabel('');

      if (html) {
        // Content/artifact workflow — show in preview
        setPreviewHtml(html);
        setPreviewFragments([]);
        setActiveTab('preview');
        setWorkflowPlan((current) => recalcWorkflowPlan(current, {
          currentStageId: 'delivery',
          currentStatus: 'complete',
          workflowComplete: true,
        }));
        const schemaDraft = extractSchema(event);
        if (schemaDraft) setSchema(schemaDraft);
        if (event.governance_report) setGovernance(event.governance_report);
        setRenderState((current) => ({ ...current, loading: false }));
        pushTimeline('Rendering', 'done');
      } else if (textResponse) {
        // Retrieval-only workflow — show text directly in chat as assistant message
        setMessages((current) => [
          ...current,
          {
            id: `${Date.now()}-${Math.random()}`,
            role: 'assistant',
            title: 'BLAIQ',
            content: textResponse,
          },
        ]);
        setRenderState((current) => ({ ...current, loading: false }));
        setWorkflowPlan((current) => recalcWorkflowPlan(current, {
          currentStageId: 'delivery',
          currentStatus: 'complete',
          workflowComplete: true,
        }));
        pushTimeline('Response', 'done');
      } else {
        // Fallback — neither HTML nor text
        setRenderState((current) => ({ ...current, loading: false }));
      }

      if (event.governance_report && !html) {
        setGovernance(event.governance_report);
        pushTimeline('Governance', event.governance_report.validation_passed ? 'done' : 'warning');
      }

      if (type === 'complete') {
        setRenderState((current) => ({ ...current, loading: false }));
        setWorkflowComplete(true);
        setWorkflowPlan((current) => recalcWorkflowPlan(current, {
          currentStageId: 'delivery',
          currentStatus: 'complete',
          workflowComplete: true,
        }));
        if (contentFlow) {
          pushTimeline('Rendering', 'done');
          if (event.governance_report) {
            pushTimeline('Governance', event.governance_report.validation_passed ? 'done' : 'warning');
          } else {
            pushTimeline('Governance', 'done');
          }
        } else {
          pushTimeline('Response', 'done');
        }
      }
    }

    if (type === 'governance' && event.governance_report) {
      setGovernance(event.governance_report);
      addLiveAgents(['governance']);
      setWorkflowPlan((current) => recalcWorkflowPlan(current, {
        currentStageId: 'governance',
        currentStatus: event.governance_report.validation_passed ? 'complete' : 'warning',
      }));
      pushTimeline('Governance', event.governance_report.validation_passed ? 'done' : 'warning');
      setThinkingLabel('Running governance checks');
    }

    if (type === 'hitl_required') {
      setIsThinking(false);
      setThinkingLabel('');
      setWorkflowPlan((current) => recalcWorkflowPlan(current, {
        currentStageId: 'hitl',
        currentStatus: 'blocked_on_user',
        hitlMode: String(event.hitl_mode || event.agent_node || event.node || 'clarification').includes('page_review')
          ? 'page_review'
          : 'clarification',
        hitlNode: event.agent_node || event.node || 'content_node',
      }));
      setHitl({
        open: true,
        questions: event.questions || [],
        answers: Object.fromEntries((event.questions || []).map((_, index) => [`q${index + 1}`, ''])),
        agentNode: event.agent_node || event.node || 'content_node',
      });
      addLiveAgents(['core', 'user']);
      pushTimeline('Awaiting input', 'blocked');
    }
  }

  async function submit() {
    const value = query.trim();
    if (!value || isSubmitting || isResuming) return;

    ensureBrowserSession();
    const sessionId = sessionIdRef.current;
    const roomNumber = roomNumberRef.current;
    const outboundHistory = buildChatHistory(messages);
    sessionIdRef.current = sessionId;
    setHasConversation(true);
    setMessages((current) => [...current, { id: `${Date.now()}`, role: 'user', content: value }]);
    setQuery('');
    setIsSubmitting(true);
    setIsThinking(true);
    setThinkingLabel('Understanding your request');
    setTimeline([{ label: 'Submit', state: 'active', at: new Date().toLocaleTimeString() }]);
    setPreviewHtml('');
    setPreviewFragments([]);
    setSchema(null);
    setGovernance(null);
    setEvidenceSummary(null);
    setWorkflowPlan(null);
    setWorkflowComplete(false);

    try {
      await submitWorkflow(
        {
          user_query: value,
          workflow_mode: workflowMode,
          session_id: sessionId,
          room_number: roomNumber,
          chat_history: outboundHistory,
          use_template_engine: true,
        },
        handleEvent
      );
    } catch (error) {
      setIsThinking(false);
      setThinkingLabel('');
      setMessages((current) => [...current, { id: `${Date.now()}-err`, role: 'system', title: 'Request failed', content: error.message || 'Unknown error' }]);
    } finally {
      setIsSubmitting(false);
    }
  }

  async function resume() {
    if (!threadId || isResuming) return;
    const answers = Object.fromEntries(Object.entries(hitl.answers).filter(([, value]) => String(value).trim()));
    if (!Object.keys(answers).length) return;

    ensureBrowserSession();
    setIsResuming(true);
    setHitl((current) => ({ ...current, open: false }));
    setActiveTab('preview');
    setRenderState((current) => ({
      ...current,
      loading: true,
      label: 'Refreshing evidence and resuming rendering',
    }));
    pushTimeline('Awaiting input', 'done');
    pushTimeline('Rendering', 'active');
    try {
      await resumeWorkflow(
        {
          thread_id: threadId,
          agent_node: hitl.agentNode,
          answers,
          session_id: sessionIdRef.current,
          room_number: roomNumberRef.current,
          chat_history: buildChatHistory(messages),
        },
        handleEvent
      );
    } catch (error) {
      setHitl((current) => ({ ...current, open: true }));
      setMessages((current) => [...current, { id: `${Date.now()}-resume`, role: 'system', title: 'Resume failed', content: error.message || 'Unknown error' }]);
    } finally {
      setIsResuming(false);
    }
  }

  function resetWorkspace() {
    setMessages([]);
    setQuery('');
    setActiveTab('plan');
    setWorkflowMode('standard');
    setThreadId('');
    setTimeline([]);
    setPreviewHtml('');
    setPreviewFragments([]);
    setSchema(null);
    setGovernance(null);
    setHitl({ open: false, questions: [], answers: {}, agentNode: 'content_node' });
    setRenderState({ loading: false, label: '', section: 0, total: 0, artifactKind: '' });
    setIsSubmitting(false);
    setIsResuming(false);
    setLastEventType('');
    setActiveAgents([]);
    setLiveAgents([]);
    setRoutingDecision(null);
    setEvidenceSummary(null);
    setHasConversation(false);
    setIsThinking(false);
    setThinkingLabel('');
    setWorkflowPlan(null);
    setWorkflowComplete(false);
    sessionIdRef.current = crypto.randomUUID();
    roomNumberRef.current = `room-${sessionIdRef.current}`;
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(
        WORKSPACE_STORAGE_KEY,
        JSON.stringify({
          sessionId: sessionIdRef.current,
          roomNumber: roomNumberRef.current,
          threadId: '',
          workflowMode: 'standard',
          query: '',
          messages: [],
          timeline: [],
        }),
      );
    }
  }

  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      const raw = window.localStorage.getItem(WORKSPACE_STORAGE_KEY);
      if (!raw) {
        ensureBrowserSession();
        return;
      }
      const saved = JSON.parse(raw);
      if (Array.isArray(saved.messages)) setMessages(saved.messages);
      if (typeof saved.threadId === 'string') setThreadId(saved.threadId);
      if (Array.isArray(saved.timeline)) setTimeline(saved.timeline);
      if (typeof saved.query === 'string') setQuery(saved.query);
      if (typeof saved.workflowMode === 'string') setWorkflowMode(saved.workflowMode);
      if (typeof saved.sessionId === 'string' && saved.sessionId) sessionIdRef.current = saved.sessionId;
      if (typeof saved.roomNumber === 'string' && saved.roomNumber) roomNumberRef.current = saved.roomNumber;
      if (saved.workflowPlan && typeof saved.workflowPlan === 'object') setWorkflowPlan(saved.workflowPlan);
      if (typeof saved.workflowComplete === 'boolean') setWorkflowComplete(saved.workflowComplete);
      if ((saved.messages || []).length > 0) setHasConversation(true);
    } catch {
      ensureBrowserSession();
    }
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    ensureBrowserSession();
    window.localStorage.setItem(
      WORKSPACE_STORAGE_KEY,
      JSON.stringify({
        sessionId: sessionIdRef.current,
        roomNumber: roomNumberRef.current,
        threadId,
        workflowMode,
        query,
        messages,
        timeline,
        workflowPlan,
        workflowComplete,
      }),
    );
  }, [messages, query, threadId, timeline, workflowMode, workflowPlan, workflowComplete]);

  useEffect(() => {
    if (!threadId) return;
    getWorkflowStatus(threadId).catch(() => {});
  }, [threadId]);

  const value = {
    messages,
    query,
    setQuery,
    activeTab,
    setActiveTab,
    workflowMode,
    setWorkflowMode,
    threadId,
    timeline,
    previewHtml,
    previewFragments,
    schema,
    governance,
    workflowPlan,
    workflowComplete,
    hitl,
    setHitl,
    renderState,
    isSubmitting,
    isResuming,
    rightRailOpen,
    submit,
    resume,
    resetWorkspace,
    activeAgents,
    liveAgents,
    routingDecision,
    evidenceSummary,
    lastEventType,
    hasConversation,
    isThinking,
    thinkingLabel,
    promptSuggestions,
    isDayMode,
    toggleDayMode,
  };

  return <BlaiqWorkspaceContext.Provider value={value}>{children}</BlaiqWorkspaceContext.Provider>;
}

export function useBlaiqWorkspace() {
  const context = useContext(BlaiqWorkspaceContext);
  if (!context) {
    throw new Error('useBlaiqWorkspace must be used within BlaiqWorkspaceProvider');
  }
  return context;
}
