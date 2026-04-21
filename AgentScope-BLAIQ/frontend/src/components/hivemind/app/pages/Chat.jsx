import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  ArrowUp,
  Bot,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  Circle,
  Clock,
  Code,
  Eye,
  FileUp,
  FileText,
  Globe,
  Loader2,
  Maximize2,
  MessageSquare,
  Minimize2,
  Paperclip,
  Play,
  Search,
  Shield,
  Sparkles,
  BookOpen,
  User,
  X,
  XCircle,
  BarChart3,
  Zap,
  Brain,
  Square,
} from 'lucide-react';
import { normalizePreviewHtml, useBlaiqWorkspace } from '../shared/blaiq-workspace-context';
import { uploadFile, cancelWorkflow } from '../shared/blaiq-client';
import { DataAnalysisResults } from '../shared/data-analysis-results';
import { BoltStyleChat } from '../shared/bolt-style-chat';

const PREFERRED_AGENT_ORDER = [
  'BLAIQ-CORE',
  'Strategic Planner',
  'Research Agent',
  'HITL Agent',
  'Content Director',
  'Visual Designer',
  'Governance',
  'System',
];

function quickChips(question) {
  const value = String(question || '').toLowerCase();
  if (value.includes('audience') || value.includes('target')) return ['Board', 'Investors', 'Enterprise buyers'];
  if (value.includes('length') || value.includes('pages') || value.includes('slides')) return ['Short', 'Standard', 'Detailed'];
  if (value.includes('focus') || value.includes('goal') || value.includes('objective')) return ['Sales', 'Strategy', 'Awareness'];
  if (value.includes('style') || value.includes('visual') || value.includes('design')) return ['Minimal', 'Executive', 'Bold'];
  return ['Use best judgement', 'Keep it concise', 'I’ll type my own answer'];
}

const THINKING_CHAR_SPEED = 4;  // reduced from 8 for 2x faster thought display
const ANSWER_CHAR_SPEED = 6;    // reduced from 12 for 2x faster answer display
const LINE_PAUSE = 60;          // reduced from 120 for faster line transitions

function useTypewriter(fullText, charSpeed, { enabled = true, startDelay = 0 } = {}) {
  const [displayed, setDisplayed] = useState('');
  const [done, setDone] = useState(false);
  const rafRef = useRef(null);
  const idxRef = useRef(0);
  const lastRef = useRef(0);

  useEffect(() => {
    if (!enabled || !fullText) {
      setDisplayed(fullText || '');
      setDone(true);
      return undefined;
    }

    setDisplayed('');
    setDone(false);
    idxRef.current = 0;
    lastRef.current = 0;

    const timeout = window.setTimeout(() => {
      function tick(now) {
        if (!lastRef.current) lastRef.current = now;
        const elapsed = now - lastRef.current;
        const charsToAdd = Math.max(1, Math.floor(elapsed / charSpeed));
        if (elapsed >= charSpeed) {
          idxRef.current = Math.min(idxRef.current + charsToAdd, fullText.length);
          setDisplayed(fullText.slice(0, idxRef.current));
          lastRef.current = now;
        }
        if (idxRef.current < fullText.length) {
          rafRef.current = window.requestAnimationFrame(tick);
        } else {
          setDone(true);
        }
      }
      rafRef.current = window.requestAnimationFrame(tick);
    }, startDelay);

    return () => {
      window.clearTimeout(timeout);
      if (rafRef.current) window.cancelAnimationFrame(rafRef.current);
    };
  }, [enabled, fullText, charSpeed, startDelay]);

  return { displayed, done };
}

function buildEvidenceThinking(evidencePack) {
  if (!evidencePack) return '';
  const lines = [];
  if (evidencePack.summary) lines.push(`Evidence summary: ${evidencePack.summary}`);
  const memory = Array.isArray(evidencePack.memory_findings) ? evidencePack.memory_findings.length : 0;
  const web = Array.isArray(evidencePack.web_findings) ? evidencePack.web_findings.length : 0;
  const docs = Array.isArray(evidencePack.doc_findings) ? evidencePack.doc_findings.length : 0;
  const total = memory + web + docs;
  lines.push(`Sources reviewed: ${total} total (${memory} memory, ${web} web, ${docs} documents)`);
  if (evidencePack.provenance?.primary_ground_truth) {
    lines.push(`Primary ground truth: ${String(evidencePack.provenance.primary_ground_truth)}`);
  }
  if (evidencePack.contradictions?.length) {
    lines.push(`Contradictions: ${evidencePack.contradictions.length}`);
  }
  if (evidencePack.open_questions?.length) {
    lines.push(`Open questions: ${evidencePack.open_questions.join(' | ')}`);
  }
  if (evidencePack.recommended_followups?.length) {
    lines.push(`Recommended follow-up: ${evidencePack.recommended_followups[0]}`);
  }
  return lines.join('\n');
}

function parseConfidenceBlock(confidenceBlock, evidencePack) {
  const fallback = {
    score: typeof evidencePack?.confidence === 'number' ? evidencePack.confidence : null,
    chunks: (evidencePack?.memory_findings?.length || 0) + (evidencePack?.web_findings?.length || 0) + (evidencePack?.doc_findings?.length || 0),
    docs: evidencePack?.provenance?.upload_sources ?? (evidencePack?.doc_findings?.length || 0),
  };

  if (!confidenceBlock) return fallback;

  const scoreMatch = confidenceBlock.match(/Score:\s*([\d.]+)/i);
  const chunksMatch = confidenceBlock.match(/Evidence Chunks:\s*(\d+)/i);
  const docsMatch = confidenceBlock.match(/Source Documents:\s*(\d+)/i);
  return {
    score: scoreMatch ? parseFloat(scoreMatch[1]) : fallback.score,
    chunks: chunksMatch ? parseInt(chunksMatch[1], 10) : fallback.chunks,
    docs: docsMatch ? parseInt(docsMatch[1], 10) : fallback.docs,
  };
}

function parseSourcesBlock(sourcesRaw, evidencePack) {
  const fromText = String(sourcesRaw || '')
    .split('\n')
    .map((line) => line.replace(/^[-•*]\s*/, '').trim())
    .filter(Boolean)
    .filter((line) => line.startsWith('[Source') || line.startsWith('[GraphRAG]'))
    .map((line) => {
      const sourceMatch = line.match(/\[Source:\s*(.+?)(?:,\s*(.+?))?\]/i);
      if (sourceMatch) {
        return {
          label: sourceMatch[1].trim(),
          detail: sourceMatch[2]?.trim() || '',
        };
      }
      return {
        label: line.replace(/^\[GraphRAG\]\s*/i, '').trim(),
        detail: '',
      };
    });

  if (fromText.length > 0) return fromText;

  return (evidencePack?.sources || []).map((source) => ({
    label: source.title || source.location || source.source_id,
    detail: [source.source_type, source.location]
      .filter(Boolean)
      .filter((value, index, arr) => arr.indexOf(value) === index)
      .join(' • '),
    source_type: source.source_type,
    source_id: source.source_id,
  }));
}

function parseAssistantResponse(content, evidencePack = null) {
  const raw = String(content || '').trim();
  const hasStructuredSections = /(\*\*ANSWER\*\*:|^ANSWER\s*:|##\s*Confidence\b|##\s*Sources\b|##\s*Context\b)/im.test(raw);

  let thinking = '';
  let answer = '';
  let sourcesRaw = '';
  let confidenceBlock = '';

  if (hasStructuredSections) {
    const analysisMatch = raw.match(/^([\s\S]*?)(?:\*\*ANSWER\*\*:|^ANSWER\s*:|##\s*Confidence\b)/im);
    if (analysisMatch) {
      thinking = analysisMatch[1].replace(/^#+\s*(ANALYSIS|Final Answer)\s*/gim, '').trim();
    }

    const answerMatch = raw.match(/(?:\*\*ANSWER\*\*:|^ANSWER\s*:)\s*([\s\S]*?)(?=\n##\s*(?:Confidence|Sources|Context)\b|\n\*\*CONTEXT\*\*:|$)/im);
    if (answerMatch) {
      answer = answerMatch[1].trim();
    } else {
      answer = raw;
    }

    const confMatch = raw.match(/##\s*Confidence\s*([\s\S]*?)(?=\n##\s*|\n\*\*|$)/im);
    if (confMatch) confidenceBlock = confMatch[1].trim();

    const sourcesMatch = raw.match(/##\s*Sources(?:\s*\(GraphRAG\))?\s*([\s\S]*?)$/im);
    if (sourcesMatch) sourcesRaw = sourcesMatch[1].trim();

    answer = answer.replace(/##\s*Confidence[\s\S]*?(?=\n##\s*Sources|\n##\s*Context|$)/im, '').trim();
    answer = answer.replace(/##\s*Sources[\s\S]*$/im, '').trim();
    answer = answer.replace(/##\s*Context[\s\S]*?(?=\n##\s*Sources|$)/im, '').trim();
  } else {
    answer = raw;
  }

  if (!thinking && evidencePack) {
    thinking = buildEvidenceThinking(evidencePack);
  }

  if (!answer && evidencePack?.summary) {
    answer = evidencePack.summary;
  }

  return {
    thinking,
    answer,
    sources: parseSourcesBlock(sourcesRaw, evidencePack),
    confidence: parseConfidenceBlock(confidenceBlock, evidencePack),
  };
}

function mdComponents(isDayMode) {
  const d = isDayMode;
  return {
    h1: ({ children }) => <h1 className={`mb-3 mt-5 text-[32px] font-[300] uppercase leading-[1.3] tracking-[0.03em] first:mt-0 ${d ? 'text-[#262626]' : 'text-white'}`}>{children}</h1>,
    h2: ({ children }) => <h2 className={`mb-2 mt-4 text-[20px] font-normal leading-[1.3] tracking-[0.02em] first:mt-0 ${d ? 'text-[#262626]' : 'text-white'}`}>{children}</h2>,
    h3: ({ children }) => <h3 className={`mb-2 mt-3 text-[16px] font-normal leading-[1.3] tracking-[0.02em] ${d ? 'text-[#262626]' : 'text-white'}`}>{children}</h3>,
    p: ({ children }) => <p className={`mb-3 text-[14px] leading-[1.3] last:mb-0 ${d ? 'text-[#262626]' : 'text-[#d4d4d4]'}`}>{children}</p>,
    strong: ({ children }) => <strong className={`font-semibold ${d ? 'text-gray-900' : 'text-white'}`}>{children}</strong>,
    em: ({ children }) => <em className={d ? 'text-gray-500' : 'text-[#a1a1a1]'}>{children}</em>,
    ul: ({ children }) => <ul className="mb-3 ml-1 space-y-1 text-[14px]">{children}</ul>,
    ol: ({ children }) => <ol className="mb-3 ml-1 list-decimal space-y-1 pl-4 text-[14px]">{children}</ol>,
    li: ({ children }) => (
      <li className="flex gap-2 leading-[1.7]">
        <span className={`mt-[10px] h-1 w-1 flex-shrink-0 rounded-full ${d ? 'bg-gray-500' : 'bg-[#525252]'}`} />
        <span className={d ? 'text-gray-800' : 'text-[#d4d4d4]'}>{children}</span>
      </li>
    ),
    a: ({ href, children }) => (
      <a href={href} className="text-[#1c69d4] underline decoration-[#1c69d4]/30 hover:decoration-[#1c69d4]" target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    ),
    code: ({ children, className }) => {
      const isBlock = className?.includes('language-');
      if (isBlock) {
        return <code className={`block overflow-x-auto rounded-lg px-3 py-2 text-[13px] ${d ? 'bg-gray-100 text-gray-900' : 'bg-[#0a0a0a] text-[#d4d4d4]'}`}>{children}</code>;
      }
      return <code className={`rounded-md px-1.5 py-0.5 text-[13px] ${d ? 'bg-gray-100 text-gray-900' : 'bg-[#1a1a1a] text-[#d4d4d4]'}`}>{children}</code>;
    },
    pre: ({ children }) => <pre className={`mb-3 overflow-x-auto rounded-lg text-[13px] ${d ? 'bg-gray-100 text-gray-900' : 'bg-[#0a0a0a] text-[#d4d4d4]'}`}>{children}</pre>,
    blockquote: ({ children }) => <blockquote className={`mb-3 border-l-2 pl-4 ${d ? 'border-gray-200 text-gray-600' : 'border-[#333] text-[#a1a1a1]'}`}>{children}</blockquote>,
    hr: () => <hr className={`my-4 ${d ? 'border-gray-200' : 'border-[#1e1e1e]'}`} />,
  };
}

function ThinkingStream({ content, onComplete, isDayMode }) {
  const d = isDayMode;
  const lines = useMemo(() => String(content || '').split('\n').map((line) => line.trim()).filter(Boolean), [content]);
  const [visibleCount, setVisibleCount] = useState(lines.length ? 1 : 0);

  useEffect(() => {
    setVisibleCount(lines.length ? 1 : 0);
  }, [content, lines.length]);

  useEffect(() => {
    if (!lines.length || visibleCount >= lines.length) {
      if (lines.length > 0) onComplete?.();
      return undefined;
    }
    const timer = window.setTimeout(() => {
      setVisibleCount((count) => Math.min(count + 1, lines.length));
    }, LINE_PAUSE);
    return () => window.clearTimeout(timer);
  }, [lines.length, visibleCount, onComplete]);

  return (
    <div className={`mt-3 overflow-hidden rounded-2xl border ${d ? 'border-gray-200 bg-gray-50' : 'border-[#1e1e1e] bg-[#111111]'}`}>
      <button
        type="button"
        className="flex w-full items-center gap-2 px-4 py-3 text-left transition-colors hover:bg-[#151515]"
      >
        <div className="flex h-5 w-5 items-center justify-center rounded-md bg-[#a855f7]/15">
          <Sparkles size={12} className="text-[#a855f7]" />
        </div>
        <span className="flex-1 text-[12px] font-semibold text-[#a855f7]">Analysis stream</span>
        <span className={`text-[10px] font-mono ${d ? 'text-gray-500' : 'text-[#6b6b6b]'}`}>{visibleCount}/{lines.length || 1}</span>
      </button>
      <div className={`border-t px-4 py-3 ${d ? 'border-gray-200' : 'border-[#1e1e1e]'}`}>
        {lines.slice(0, visibleCount).map((line, index) => (
          <div key={`${index}-${line}`} className={`mb-1.5 text-[12px] leading-relaxed last:mb-0 ${d ? 'text-gray-700' : 'text-[#a1a1a1]'}`}>
            {line}
          </div>
        ))}
      </div>
    </div>
  );
}

function ThinkingCollapsed({ content, isDayMode }) {
  const d = isDayMode;
  const lineCount = useMemo(() => String(content || '').split('\n').map((line) => line.trim()).filter(Boolean).length, [content]);
  const preview = useMemo(() => String(content || '').split('\n').find((line) => line.trim()) || 'Analysis complete.', [content]);

  return (
    <div className={`mt-3 rounded-2xl border px-4 py-3 ${d ? 'border-gray-200 bg-gray-50' : 'border-[#1e1e1e] bg-[#111111]'}`}>
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[12px] font-semibold text-[#a855f7]">Analysis complete</div>
          <div className={`mt-1 truncate text-[12px] ${d ? 'text-gray-600' : 'text-[#a1a1a1]'}`}>{preview}</div>
        </div>
        <span className={`shrink-0 text-[10px] font-mono ${d ? 'text-gray-400' : 'text-[#6b6b6b]'}`}>{lineCount} lines</span>
      </div>
    </div>
  );
}

function ConfidenceBadge({ confidence, visible, isDayMode }) {
  const d = isDayMode;
  if (!visible || confidence?.score === null || confidence?.score === undefined) return null;
  const pct = Math.round(Number(confidence.score || 0) * 100);
  const color = pct >= 75 ? '#10b981' : pct >= 50 ? '#f59e0b' : '#ef4444';

  return (
    <div className={`mt-4 flex items-center gap-4 rounded-2xl border px-4 py-3 ${d ? 'border-gray-200 bg-white/80' : 'border-[#1e1e1e] bg-[#111111]'}`}>
      <div className="flex items-center gap-2">
        <div className="relative h-7 w-7">
          <svg className="h-7 w-7 -rotate-90" viewBox="0 0 28 28">
            <circle cx="14" cy="14" r="11" fill="none" stroke={d ? '#e5e7eb' : '#1e1e1e'} strokeWidth="2.5" />
            <circle
              cx="14"
              cy="14"
              r="11"
              fill="none"
              stroke={color}
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeDasharray={`${2 * Math.PI * 11}`}
              strokeDashoffset={`${2 * Math.PI * 11 * (1 - pct / 100)}`}
              className="transition-all duration-1000"
            />
          </svg>
          <span className="absolute inset-0 flex items-center justify-center text-[8px] font-bold" style={{ color }}>{pct}%</span>
        </div>
        <span className={`text-[12px] font-medium ${d ? 'text-gray-600' : 'text-[#a1a1a1]'}`}>Confidence</span>
      </div>
      {confidence.chunks !== null && confidence.chunks !== undefined ? (
        <div className={`flex items-center gap-1.5 text-[11px] ${d ? 'text-gray-500' : 'text-[#6b6b6b]'}`}>
          <FileText size={11} />
          <span>{confidence.chunks} chunks</span>
        </div>
      ) : null}
      {confidence.docs !== null && confidence.docs !== undefined ? (
        <div className={`flex items-center gap-1.5 text-[11px] ${d ? 'text-gray-500' : 'text-[#6b6b6b]'}`}>
          <BookOpen size={11} />
          <span>{confidence.docs} docs</span>
        </div>
      ) : null}
    </div>
  );
}

function SourcesDropdown({ sources, visible, isDayMode }) {
  const d = isDayMode;
  const [open, setOpen] = useState(false);

  if (!visible || !sources || sources.length === 0) return null;

  return (
    <div className="mt-4">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className={`flex w-full items-center gap-2 rounded-2xl border px-4 py-3 text-left transition-colors ${d ? 'border-gray-200 bg-white/80 hover:bg-gray-50' : 'border-[#1e1e1e] bg-[#111111] hover:bg-[#151515]'}`}
      >
        <div className="flex h-5 w-5 items-center justify-center rounded-md bg-blue-500/15">
          <BookOpen size={12} className="text-blue-400" />
        </div>
        <span className="flex-1 text-[12px] font-semibold text-blue-400">Sources ({sources.length})</span>
        <span className={`rounded-md px-2 py-0.5 text-[10px] font-mono ${d ? 'bg-blue-50 text-blue-500' : 'bg-blue-500/10 text-blue-400'}`}>Evidence</span>
        <ChevronDown size={14} className={`text-[#525252] transition-transform duration-200 ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className={`mt-1 rounded-b-2xl border border-t-0 px-2 py-2 ${d ? 'border-gray-200 bg-white' : 'border-[#1e1e1e] bg-[#0f0f0f]'}`}>
          {sources.map((source, index) => (
            <div key={`${source.label}-${index}`} className={`flex items-start gap-3 rounded-xl px-3 py-2 transition-colors ${d ? 'hover:bg-gray-50' : 'hover:bg-[#151515]'}`}>
              <div className="mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-md bg-[#1a1a1a] text-[10px] font-bold text-[#8b8b8b]">
                {index + 1}
              </div>
              <div className="min-w-0 flex-1">
                <div className={`truncate text-[12px] font-medium ${d ? 'text-gray-800' : 'text-[#d4d4d4]'}`}>{source.label}</div>
                {source.detail ? (
                  <div className={`text-[11px] ${d ? 'text-gray-500' : 'text-[#6b6b6b]'}`}>{source.detail}</div>
                ) : null}
              </div>
              <FileText size={12} className="mt-1 flex-shrink-0 text-[#333]" />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StreamedAnswer({ content, enabled, onComplete, isDayMode }) {
  const d = isDayMode;
  const { displayed, done } = useTypewriter(content, ANSWER_CHAR_SPEED, { enabled, startDelay: 90 });  // reduced from 180

  useEffect(() => {
    if (done) onComplete?.();
  }, [done, onComplete]);

  return (
    <div className={`mt-4 rounded-2xl border px-5 py-4 ${d ? 'border-gray-200 bg-white/80 shadow-sm' : 'border-[#1e1e1e] bg-[#0f0f0f]'}`}>
      <div className="mb-3 flex items-center gap-2">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-[#F95C4B]/15">
          <Bot size={13} className="text-[#F95C4B]" />
        </div>
        <span className={`text-[13px] font-semibold ${d ? 'text-gray-900' : 'text-white'}`}>BLAIQ</span>
        {!done ? (
          <span className="relative ml-1 flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#F95C4B] opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-[#F95C4B]" />
          </span>
        ) : null}
      </div>
      <div className={`prose-blaiq ${d ? 'text-gray-900' : 'text-white'}`}>
        <Markdown remarkPlugins={[remarkGfm]} components={mdComponents(d)}>
          {displayed}
        </Markdown>
      </div>
      {!done ? <span className="inline-block h-[14px] w-[1px] animate-pulse bg-blue-400 align-middle" /> : null}
    </div>
  );
}

function FinalAnswerCard({ taskId, content, isDayMode, hypothesisTree, hasStreamed, onStreamComplete }) {
  const d = isDayMode;
  // Use raw content directly — don't parse with parseAssistantResponse which
  // strips markdown thinking it's "analysis" section. The deep research agent
  // returns clean markdown answers, not **ANSWER**: formatted responses.
  const { displayed, done } = useTypewriter(content, ANSWER_CHAR_SPEED, {
    enabled: !hasStreamed,
    startDelay: 60,  // reduced from 120 for faster streaming
  });

  useEffect(() => {
    if (done && !hasStreamed) {
      onStreamComplete?.(taskId);
    }
  }, [done, hasStreamed, onStreamComplete, taskId]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      className="pt-2"
    >
      <div className={`rounded-3xl border px-5 py-4 ${d ? 'border-gray-200 bg-white/90 shadow-sm' : 'border-[#1e1e1e] bg-[#0f0f0f]'}`}>
        <div className="mb-3 flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[#F95C4B]/15">
            <Bot size={14} className="text-[#F95C4B]" />
          </div>
          <div>
            <div className={`text-[13px] font-semibold ${d ? 'text-gray-900' : 'text-white'}`}>Final answer</div>
            <div className={`text-[10px] ${d ? 'text-gray-400' : 'text-[#6b6b6b]'}`}>Streamed as a plain assistant message</div>
          </div>
        </div>

        <div className={`prose-blaiq ${d ? 'text-gray-900' : 'text-white'}`}>
          <Markdown remarkPlugins={[remarkGfm]} components={mdComponents(d)}>
            {displayed}
          </Markdown>
        </div>
        {!done ? <span className="inline-block h-[14px] w-[1px] animate-pulse bg-blue-400 align-middle" /> : null}

        {/* Hypothesis Tree Visualization (for finance analysis mode) */}
        {hypothesisTree && <HypothesisTree hypothesisTree={hypothesisTree} isDayMode={d} />}
      </div>
    </motion.div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   RIGHT PANEL — Steps progress + Artifact preview (tabbed)
   ═══════════════════════════════════════════════════════════════════════════ */

function StepIcon({ status, size = 16 }) {
  if (status === 'done') {
    return (
      <div className="relative flex items-center justify-center">
        <div className="absolute inset-0 rounded-full bg-emerald-500/20 animate-ping" style={{ animationDuration: '2s', animationIterationCount: 1 }} />
        <div className="relative flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500/10 border border-emerald-500/30">
          <CheckCircle size={13} className="text-emerald-400" />
        </div>
      </div>
    );
  }
  if (status === 'active') {
    return (
      <div className="relative flex items-center justify-center">
        <div className="absolute h-8 w-8 rounded-full bg-blue-500/15 animate-pulse" />
        <div className="relative flex h-6 w-6 items-center justify-center rounded-full bg-blue-500/20 border border-blue-400/40 shadow-[0_0_12px_rgba(59,130,246,0.4)]">
          <Loader2 size={12} className="animate-spin text-blue-400" />
        </div>
      </div>
    );
  }
  if (status === 'error') {
    return (
      <div className="flex h-6 w-6 items-center justify-center rounded-full bg-red-500/10 border border-red-500/30">
        <XCircle size={13} className="text-red-400" />
      </div>
    );
  }
  return (
    <div className="flex h-6 w-6 items-center justify-center rounded-full border border-gray-200/30 bg-gray-100/5">
      <Circle size={10} className="text-gray-300/40" />
    </div>
  );
}

/* ─── Steps tab content ──────────────────────────────────────────────────── */

function StepsContent({ task, isDayMode }) {
  const d = isDayMode;
  const { resume } = useBlaiqWorkspace();
  const doneCount = task.steps.filter((s) => s.status === 'done').length;
  const total = task.steps.length;
  const pct = total > 0 ? Math.round((doneCount / total) * 100) : 0;

  return (
    <div className="flex-1 overflow-y-auto">
      {/* Mission header */}
      <div className={`px-4 py-4 border-b ${d ? 'border-gray-100' : 'border-[#1e1e1e]'}`}>
        <div className="flex items-center gap-2">
          <div className={`text-[10px] font-mono uppercase tracking-[0.15em] ${d ? 'text-gray-400' : 'text-[#525252]'}`}>Mission</div>
          <div className={`h-px flex-1 ${d ? 'bg-gray-100' : 'bg-[#1e1e1e]'}`} />
          <div className={`text-[10px] font-mono tabular-nums ${
            task.status === 'complete' ? 'text-emerald-500' : task.status === 'error' ? 'text-red-400' : 'text-blue-400'
          }`}>
            {pct}%
          </div>
        </div>
        <div className={`mt-2 text-[13px] font-semibold leading-snug ${d ? 'text-gray-900' : 'text-white'}`}>
          {task.query.length > 55 ? task.query.slice(0, 55) + '...' : task.query}
        </div>
        {/* Segmented progress bar */}
        <div className="mt-3 flex items-center gap-1">
          {task.steps.map((step) => {
            const segDone = step.status === 'done';
            const segActive = step.status === 'active';
            const segError = step.status === 'error';
            return (
              <div
                key={step.id}
                className={`h-1.5 flex-1 rounded-full transition-all duration-500 ${
                  segDone ? 'bg-emerald-500' :
                  segActive ? 'bg-blue-500 animate-pulse' :
                  segError ? 'bg-red-400' :
                  d ? 'bg-gray-100' : 'bg-[#1e1e1e]'
                }`}
                title={step.label}
              />
            );
          })}
        </div>
      </div>

      {/* Mission checkpoints */}
      <div className="px-3 py-2 space-y-0">
        {task.steps.map((step, i) => {
          const isActive = step.status === 'active';
          const isDone = step.status === 'done';
          const isError = step.status === 'error';
          const isPending = !isActive && !isDone && !isError;
          const isLast = i === task.steps.length - 1;

          return (
            <div key={step.id} className="relative flex gap-3">
              {/* Connector line */}
              {!isLast && (
                <div
                  className={`absolute left-[11px] top-[30px] w-px ${
                    isDone ? 'bg-emerald-500/30' : isActive ? 'bg-blue-500/20' : d ? 'bg-gray-100' : 'bg-[#1a1a1a]'
                  }`}
                  style={{ height: 'calc(100% - 6px)' }}
                />
              )}

              {/* Checkpoint icon */}
              <div className="relative z-10 flex-shrink-0 pt-2">
                <StepIcon status={step.status} />
              </div>

              {/* Content */}
              <div className={`flex-1 rounded-xl px-2 py-2 transition-all ${
                isActive ? (d ? 'bg-blue-50/80' : 'bg-blue-950/20') : ''
              }`}>
                <div className="flex items-center justify-between">
                  <div className={`text-[12px] font-semibold ${
                    isDone ? (d ? 'text-gray-500' : 'text-[#7a7a7a]')
                    : isActive ? (d ? 'text-gray-900' : 'text-white')
                    : (d ? 'text-gray-300' : 'text-[#3a3a3a]')
                  }`}>
                    {step.label}
                  </div>
                  {isDone && (
                    <span className={`text-[9px] font-mono uppercase tracking-wider ${d ? 'text-emerald-600' : 'text-emerald-500'}`}>
                      done
                    </span>
                  )}
                  {isActive && (
                    <span className="text-[9px] font-mono uppercase tracking-wider text-blue-400 animate-pulse">
                      live
                    </span>
                  )}
                  {isPending && (
                    <span className={`text-[9px] font-mono tabular-nums ${d ? 'text-gray-300' : 'text-[#333]'}`}>
                      {i + 1}/{total}
                    </span>
                  )}
                </div>
                {(isActive || isDone) && (
                  <div className="mt-0.5">
                    <div className={`text-[10px] ${
                      isActive ? 'text-blue-400' : d ? 'text-gray-400' : 'text-[#525252]'
                    }`}>
                      {step.agent}
                      {isActive && step.detail ? ` — ${step.detail}` : ''}
                      {isDone && step.detail ? ` — ${step.detail}` : ''}
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Governance */}
      {task.governanceReport && (
        <div className={`mx-3 mb-3 rounded-xl border px-3 py-3 ${
          task.governanceReport.approved
            ? d ? 'border-emerald-200 bg-emerald-50' : 'border-emerald-800/30 bg-emerald-950/20'
            : d ? 'border-orange-200 bg-orange-50' : 'border-orange-800/30 bg-orange-950/20'
        }`}>
          <div className="flex items-center gap-2">
            <Shield size={13} className={task.governanceReport.approved ? 'text-emerald-500' : 'text-orange-500'} />
            <span className={`text-[11px] font-semibold ${
              task.governanceReport.approved ? (d ? 'text-emerald-700' : 'text-emerald-400') : (d ? 'text-orange-700' : 'text-orange-400')
            }`}>
              {task.governanceReport.approved ? 'Governance Approved' : 'Revision Required'}
            </span>
          </div>
          <div className={`mt-1 ml-[21px] text-[10px] ${task.governanceReport.approved ? (d ? 'text-emerald-600' : 'text-emerald-500') : (d ? 'text-orange-600' : 'text-orange-500')}`}>
            Readiness score: {task.governanceReport.readiness_score}
          </div>
          {task.governanceReport.notes?.map((note, i) => (
            <div key={i} className={`ml-[21px] text-[10px] ${task.governanceReport.approved ? (d ? 'text-emerald-600' : 'text-emerald-500/80') : (d ? 'text-orange-600' : 'text-orange-500/80')}`}>
              {note}
            </div>
          ))}
        </div>
      )}

      {/* HITL / Error actions */}
      {task.status === 'blocked' && (
        <div className={`mx-3 mb-3 rounded-xl border px-3 py-3 ${d ? 'border-amber-200 bg-amber-50' : 'border-amber-800/30 bg-amber-950/20'}`}>
          <div className={`text-[11px] font-semibold ${d ? 'text-amber-800' : 'text-amber-400'}`}>Waiting for input</div>
          <button
            type="button"
            onClick={() => resume(task.id, 'User approved')}
            className="mt-2 flex items-center gap-1.5 rounded-lg bg-amber-100 px-3 py-1.5 text-[11px] font-medium text-amber-800 hover:bg-amber-200 transition-colors"
          >
            <Play size={10} /> Continue
          </button>
        </div>
      )}
      {task.status === 'error' && task.error && (
        <div className={`mx-3 mb-3 rounded-xl border px-3 py-3 ${d ? 'border-red-200 bg-red-50' : 'border-red-800/30 bg-red-950/20'}`}>
          <div className={`text-[11px] font-semibold ${d ? 'text-red-700' : 'text-red-400'}`}>Error</div>
          <div className={`mt-1 text-[10px] ${d ? 'text-red-600' : 'text-red-500'}`}>{task.error}</div>
          <button
            type="button"
            onClick={() => resume(task.id, 'Retry')}
            className="mt-2 flex items-center gap-1.5 rounded-lg bg-red-100 px-3 py-1.5 text-[11px] font-medium text-red-700 hover:bg-red-200 transition-colors"
          >
            <Play size={10} /> Retry
          </button>
        </div>
      )}
    </div>
  );
}

/* ─── Preview tab content ─────────────────────────────────────────────────── */

function PreviewContent({ task, isDayMode }) {
  const iframeRef = useRef(null);
  const [maximized, setMaximized] = useState(false);
  const [showCode, setShowCode] = useState(false);

  const rawPreviewHtml = (() => {
    if (task.artifact?.html) return task.artifact.html;
    const sections = task.artifactSections || [];
    if (sections.length === 0) return '';
    const fragments = sections.map((s) => s.html_fragment || '').filter(Boolean).join('\n');
    if (!fragments) return '';
    return `<!doctype html><html><head><meta charset="UTF-8"/><style>body{font-family:system-ui,sans-serif;margin:0;padding:40px;background:#f3efe7;color:#101010}section{margin-bottom:24px;padding:24px;border-radius:16px;background:#fff}${task.artifact?.css || ''}</style></head><body>${fragments}</body></html>`;
  })();
  const previewHtml = rawPreviewHtml
    ? normalizePreviewHtml(rawPreviewHtml, { title: task.artifact?.title || task.query || 'Artifact preview', css: task.artifact?.css || '' })
    : '';

  const hasPreview = Boolean(rawPreviewHtml.trim());

  useEffect(() => {
    if (hasPreview && iframeRef.current && !showCode) {
      const doc = iframeRef.current.contentDocument || iframeRef.current.contentWindow?.document;
      if (doc) { doc.open(); doc.write(previewHtml); doc.close(); }
    }
  }, [previewHtml, hasPreview, showCode]);

  const formatHtml = (html) => {
    let formatted = html;
    let indent = 0;
    return formatted
      .split('\n')
      .map((line) => {
        const trimmed = line.trim();
        if (!trimmed) return '';
        if (trimmed.startsWith('</')) indent = Math.max(0, indent - 1);
        const result = '  '.repeat(indent) + trimmed;
        if (trimmed.startsWith('<') && !trimmed.startsWith('</') && !trimmed.endsWith('/>')) {
          if (!trimmed.includes('<!') && !trimmed.includes('<?')) indent++;
        }
        return result;
      })
      .filter(Boolean)
      .join('\n');
  };

  if (!hasPreview) {
    return (
      <div className="flex flex-1 items-center justify-center text-center">
        <div>
          <div className={`mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-2xl ${isDayMode ? 'bg-gray-100' : 'bg-[#1e1e1e]'}`}>
            <Globe size={22} className={isDayMode ? 'text-gray-300' : 'text-[#3a3a3a]'} />
          </div>
          <div className={`text-[13px] font-medium ${isDayMode ? 'text-gray-400' : 'text-[#525252]'}`}>Preview</div>
          <div className={`mt-1 text-[11px] ${isDayMode ? 'text-gray-300' : 'text-[#3a3a3a]'}`}>
            {task.status === 'running' ? 'Generating artifact...' : 'No artifact yet'}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`flex flex-1 flex-col ${maximized ? 'fixed inset-0 z-50 bg-white' : ''}`}>
      <div className={`flex items-center justify-between px-3 py-2 border-b ${isDayMode ? 'border-gray-100' : 'border-[#1e1e1e]'}`}>
        <div className="flex items-center gap-2">
          <div className={`h-2 w-2 rounded-full ${task.status === 'complete' ? 'bg-emerald-400' : 'bg-blue-400 animate-pulse'}`} />
          <span className={`text-[12px] font-medium ${isDayMode ? 'text-gray-700' : 'text-[#a1a1a1]'}`}>
            {task.artifact?.title || 'Artifact'}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button type="button" onClick={() => setShowCode((v) => !v)} className={`rounded-lg p-1.5 ${isDayMode ? 'text-gray-400 hover:bg-gray-50' : 'text-[#525252] hover:bg-[#1e1e1e]'}`} title="Toggle code view">
            <Code size={13} />
          </button>
          <button type="button" onClick={() => setMaximized((v) => !v)} className={`rounded-lg p-1.5 ${isDayMode ? 'text-gray-400 hover:bg-gray-50' : 'text-[#525252] hover:bg-[#1e1e1e]'}`}>
            {maximized ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-hidden bg-[#050505]">
        {showCode ? (
          <pre className={`h-full w-full overflow-auto p-4 font-mono text-xs ${isDayMode ? 'bg-gray-50 text-gray-900' : 'bg-[#1a1a1a] text-[#e0e0e0]'}`}>
            {formatHtml(rawPreviewHtml)}
          </pre>
        ) : (
          <iframe
            ref={iframeRef}
            title="preview"
            className="h-full w-full border-0"
            sandbox="allow-scripts allow-same-origin allow-popups"
            style={{ background: 'transparent' }}
          />
        )}
      </div>
    </div>
  );
}

/* ─── Combined right panel with tabs ──────────────────────────────────────── */

function RightPanel({ task, onClose }) {
  const { isDayMode } = useBlaiqWorkspace();
  const d = isDayMode;
  const [tab, setTab] = useState('steps');

  // Auto-switch to preview when artifact arrives
  useEffect(() => {
    if (task.artifact?.html || (task.artifactSections || []).length > 0) {
      setTab('preview');
    }
  }, [task.artifact?.html, task.artifactSections?.length]);

  return (
    <div className={`flex h-full flex-col ${d ? 'bg-white' : 'bg-[#0f0f0f]'}`}>
      {/* Tab bar */}
      <div className={`flex items-center justify-between border-b px-3 py-2 ${d ? 'border-gray-100' : 'border-[#1e1e1e]'}`}>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setTab('steps')}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11px] font-medium transition-colors ${
              tab === 'steps'
                ? d ? 'bg-blue-50 text-blue-700' : 'bg-blue-950/30 text-blue-400'
                : d ? 'text-gray-400 hover:bg-gray-50 hover:text-gray-600' : 'text-[#525252] hover:bg-[#1a1a1a] hover:text-[#a1a1a1]'
            }`}
          >
            <Clock size={12} /> Progress
          </button>
          <button
            type="button"
            onClick={() => setTab('preview')}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11px] font-medium transition-colors ${
              tab === 'preview'
                ? d ? 'bg-blue-50 text-blue-700' : 'bg-blue-950/30 text-blue-400'
                : d ? 'text-gray-400 hover:bg-gray-50 hover:text-gray-600' : 'text-[#525252] hover:bg-[#1a1a1a] hover:text-[#a1a1a1]'
            }`}
          >
            <Eye size={12} /> Preview
          </button>
        </div>
        <button type="button" onClick={onClose} className={`rounded-lg p-1.5 ${d ? 'text-gray-400 hover:bg-gray-50' : 'text-[#525252] hover:bg-[#1a1a1a]'}`}>
          <X size={14} />
        </button>
      </div>

      {/* Tab content */}
      {tab === 'steps' && <StepsContent task={task} isDayMode={d} />}
      {tab === 'preview' && <PreviewContent task={task} isDayMode={d} />}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   CENTER — Agent conversation
   ═══════════════════════════════════════════════════════════════════════════ */

function agentColor(agent) {
  const a = String(agent || '').toLowerCase();
  if (a.includes('strateg')) return { bg: 'bg-purple-100', text: 'text-purple-700', dark: 'bg-purple-900/20', darkText: 'text-purple-400' };
  if (a.includes('research')) return { bg: 'bg-cyan-100', text: 'text-cyan-700', dark: 'bg-cyan-900/20', darkText: 'text-cyan-400' };
  if (a.includes('visual') || a.includes('vangogh')) return { bg: 'bg-pink-100', text: 'text-pink-700', dark: 'bg-pink-900/20', darkText: 'text-pink-400' };
  if (a.includes('govern')) return { bg: 'bg-emerald-100', text: 'text-emerald-700', dark: 'bg-emerald-900/20', darkText: 'text-emerald-400' };
  return { bg: 'bg-gray-100', text: 'text-gray-700', dark: 'bg-[#1e1e1e]', darkText: 'text-[#a1a1a1]' };
}

function buildAgentStreams(messages) {
  const byAgent = new Map();

  for (const msg of messages) {
    if (!String(msg?.content || '').trim()) {
      continue;
    }
    const agent = msg.agent || 'System';
    if (!byAgent.has(agent)) {
      byAgent.set(agent, []);
    }
    byAgent.get(agent).push(msg);
  }

  const orderedAgents = [
    ...PREFERRED_AGENT_ORDER.filter((agent) => byAgent.has(agent)),
    ...Array.from(byAgent.keys()).filter((agent) => !PREFERRED_AGENT_ORDER.includes(agent)),
  ];

  return orderedAgents.map((agent) => ({
    agent,
    entries: byAgent.get(agent) || [],
  }));
}

function AgentStreamRow({ agent, entries, isDayMode, active, expanded, onToggle, visibleText }) {
  const d = isDayMode;
  const colors = agentColor(agent);
  const lastEntry = entries[entries.length - 1];

  return (
    <div className={`py-3 ${active ? (d ? 'text-gray-900' : 'text-white') : ''}`}>
      <div className="flex items-start gap-3">
        <button
          type="button"
          onClick={onToggle}
          className={`mt-0.5 rounded-full p-1 transition-colors ${d ? 'text-gray-400 hover:bg-gray-100' : 'text-[#5b5b5b] hover:bg-[#171717]'}`}
          aria-label={expanded ? `Collapse ${agent} logs` : `Expand ${agent} logs`}
        >
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
        <div className={`flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full ${d ? colors.bg : colors.dark}`}>
          {active ? <Loader2 size={14} className={`animate-spin ${d ? colors.text : colors.darkText}`} /> : <Bot size={14} className={d ? colors.text : colors.darkText} />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className={`text-[12px] font-semibold ${d ? colors.text : colors.darkText}`}>{agent}</span>
            <span className={`text-[10px] ${d ? 'text-gray-400' : 'text-[#5b5b5b]'}`}>
              {lastEntry?.at ? new Date(lastEntry.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : ''}
            </span>
            {active ? (
              <span className={`text-[10px] ${d ? 'text-blue-500' : 'text-blue-300'}`}>live</span>
            ) : null}
          </div>
          <div className={`mt-1 text-[13px] leading-relaxed ${d ? 'text-gray-700' : 'text-[#d4d4d4]'}`}>
            {visibleText}
            {active ? <span className={`ml-0.5 inline-block h-[14px] w-[1px] animate-pulse align-middle ${d ? 'bg-blue-500' : 'bg-blue-300'}`} /> : null}
          </div>
          {expanded && entries.length > 1 ? (
            <div className={`mt-3 space-y-2 border-l pl-4 ${d ? 'border-gray-200' : 'border-[#242424]'}`}>
              {entries.map((entry) => (
                <div key={entry.id} className="space-y-0.5">
                  <div className={`text-[10px] ${d ? 'text-gray-400' : 'text-[#5b5b5b]'}`}>
                    {entry.at ? new Date(entry.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : ''}
                  </div>
                  <div className={`text-[12px] leading-relaxed ${d ? 'text-gray-500' : 'text-[#a1a1a1]'}`}>{entry.content}</div>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function HypothesisTree({ hypothesisTree, isDayMode }) {
  const [open, setOpen] = useState(false);
  const d = isDayMode;

  if (!hypothesisTree || !Array.isArray(hypothesisTree) || hypothesisTree.length === 0) {
    return null;
  }

  // Calculate stats
  const totalNodes = hypothesisTree.reduce((acc, node) => {
    const countNode = (n) => 1 + (n.children || []).reduce((sum, c) => sum + countNode(c), 0);
    return acc + countNode(node);
  }, 0);

  const verified = hypothesisTree.reduce((acc, node) => {
    const countStatus = (n) => (n.status === 'verified' ? 1 : 0) + (n.children || []).reduce((sum, c) => sum + countStatus(c), 0);
    return acc + countStatus(node);
  }, 0);

  const refuted = hypothesisTree.reduce((acc, node) => {
    const countStatus = (n) => (n.status === 'refuted' ? 1 : 0) + (n.children || []).reduce((sum, c) => sum + countStatus(c), 0);
    return acc + countStatus(node);
  }, 0);

  const uncertain = totalNodes - verified - refuted;

  function renderNode(node, depth = 0, isLast = true, prefix = '') {
    const statusIcon = node.status === 'verified' ? '✓' : node.status === 'refuted' ? '✗' : '?';
    const statusColor = node.status === 'verified' ? 'text-emerald-500' : node.status === 'refuted' ? 'text-red-400' : 'text-amber-500';
    const connector = isLast ? '└── ' : '├── ';
    const extension = isLast ? '    ' : '│   ';

    return (
      <div key={node.id} className="font-mono text-[11px] leading-relaxed">
        <div className={`flex items-start gap-2 ${d ? 'text-gray-700' : 'text-[#a1a1a1]'}`}>
          <span className={d ? 'text-gray-400' : 'text-[#525252]'}>{prefix}{connector}</span>
          <span className={`font-bold ${statusColor}`}>[{statusIcon}]</span>
          <span className="flex-1">
            <span className={`font-semibold ${d ? 'text-gray-900' : 'text-white'}`}>{node.id}</span>
            <span className={`ml-2 ${d ? 'text-gray-600' : 'text-[#8a8a8a]'}`}>
              {node.statement.length > 80 ? node.statement.slice(0, 80) + '...' : node.statement}
            </span>
          </span>
        </div>
        {node.failure_reason && node.status !== 'verified' && (
          <div className={`ml-6 mt-1 text-[10px] ${d ? 'text-gray-500' : 'text-[#6b6b6b]'}`}>
            Reason: {node.failure_reason}
          </div>
        )}
        {(node.children || []).length > 0 && (
          <div>
            {node.children.map((child, i) =>
              renderNode(child, depth + 1, i === node.children.length - 1, prefix + extension)
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="mt-4 rounded-2xl border overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={`w-full flex items-center justify-between px-4 py-3 transition-colors ${
          d ? 'bg-gray-50 hover:bg-gray-100 border-b border-gray-200' : 'bg-[#161616] hover:bg-[#1e1e1e] border-b border-[#2a2a2a]'
        }`}
      >
        <div className="flex items-center gap-3">
          <BookOpen size={16} className={d ? 'text-blue-500' : 'text-blue-400'} />
          <div className="flex items-center gap-2 text-[13px]">
            <span className={`font-semibold ${d ? 'text-gray-900' : 'text-white'}`}>Hypothesis Tree</span>
            <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
              d ? 'bg-blue-100 text-blue-700' : 'bg-blue-900/30 text-blue-300'
            }`}>
              {totalNodes} nodes
            </span>
            <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
              d ? 'bg-emerald-100 text-emerald-700' : 'bg-emerald-900/30 text-emerald-300'
            }`}>
              ✓ {verified}
            </span>
            <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
              d ? 'bg-red-100 text-red-700' : 'bg-red-900/30 text-red-300'
            }`}>
              ✗ {refuted}
            </span>
            <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
              d ? 'bg-amber-100 text-amber-700' : 'bg-amber-900/30 text-amber-300'
            }`}>
              ? {uncertain}
            </span>
          </div>
        </div>
        <svg
          width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
          className={`transition-transform ${open ? 'rotate-180' : ''} ${d ? 'text-gray-400' : 'text-[#525252]'}`}
        >
          <path d="M6 9l6 6 6-6"/>
        </svg>
      </button>

      {open && (
        <div className={`p-4 space-y-3 ${d ? 'bg-white' : 'bg-[#0f0f0f]'}`}>
          {hypothesisTree.map((node, i) =>
            renderNode(node, 0, i === hypothesisTree.length - 1)
          )}
        </div>
      )}
    </div>
  );
}

function EvidenceMetadata({ evidencePack, isDayMode }) {
  const [open, setOpen] = useState(false);
  const d = isDayMode;
  const memCount = (evidencePack.memory_findings || []).length;
  const webCount = (evidencePack.web_findings || []).length;
  const docCount = (evidencePack.doc_findings || []).length;
  const totalSources = memCount + webCount + docCount;
  const confidence = evidencePack.confidence || 0;
  const prov = evidencePack.provenance || {};

  const confidenceColor = confidence >= 0.7 ? 'text-emerald-500' : confidence >= 0.4 ? 'text-amber-500' : 'text-red-400';
  const confidenceLabel = confidence >= 0.7 ? 'High' : confidence >= 0.4 ? 'Medium' : 'Low';

  return (
    <div className="pl-10 pt-3">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-3 rounded-xl px-3 py-2 text-[11px] transition-colors ${
          d ? 'bg-gray-50 hover:bg-gray-100 text-gray-500' : 'bg-[#161616] hover:bg-[#1e1e1e] text-[#7a7a7a]'
        }`}
      >
        <span className={`font-semibold ${confidenceColor}`}>{confidenceLabel} confidence</span>
        <span className={d ? 'text-gray-300' : 'text-[#333]'}>|</span>
        <span>{totalSources} sources</span>
        <span className={d ? 'text-gray-300' : 'text-[#333]'}>|</span>
        <span>{Math.round(confidence * 100)}%</span>
        <svg
          width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
          className={`transition-transform ${open ? 'rotate-180' : ''}`}
        >
          <path d="M6 9l6 6 6-6"/>
        </svg>
      </button>

      {open && (
        <div className={`mt-2 rounded-xl border p-3 text-[11px] space-y-2 ${
          d ? 'border-gray-100 bg-gray-50 text-gray-600' : 'border-[#222] bg-[#111] text-[#888]'
        }`}>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <div className={`font-semibold ${d ? 'text-gray-900' : 'text-white'}`}>{memCount}</div>
              <div>Memory</div>
            </div>
            <div>
              <div className={`font-semibold ${d ? 'text-gray-900' : 'text-white'}`}>{webCount}</div>
              <div>Web</div>
            </div>
            <div>
              <div className={`font-semibold ${d ? 'text-gray-900' : 'text-white'}`}>{docCount}</div>
              <div>Documents</div>
            </div>
          </div>
          <div className={`border-t pt-2 ${d ? 'border-gray-200' : 'border-[#222]'}`}>
            <div className="flex justify-between">
              <span>Ground truth</span>
              <span className={`font-medium ${d ? 'text-gray-800' : 'text-white'}`}>{prov.primary_ground_truth || 'memory'}</span>
            </div>
            {prov.graph_traversals > 0 && (
              <div className="flex justify-between">
                <span>Graph traversals</span>
                <span className={`font-medium ${d ? 'text-gray-800' : 'text-white'}`}>{prov.graph_traversals}</span>
              </div>
            )}
          </div>
          {evidencePack.freshness && (
            <div className={`border-t pt-2 ${d ? 'border-gray-200' : 'border-[#222]'}`}>
              <div className="flex justify-between">
                <span>Memory fresh</span>
                <span>{evidencePack.freshness.memory_is_fresh ? '✓' : '✗'}</span>
              </div>
              <div className="flex justify-between">
                <span>Web verified</span>
                <span>{evidencePack.freshness.web_verified ? '✓' : '✗'}</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ConversationArea({ task, sessionTasks }) {
  const { submit, isSubmitting, isDayMode, previewOpen, setPreviewOpen, updateHitlAnswer, updateHitlAnswerMode, updateHitlIndex, markFinalAnswerStreamed, resume } = useBlaiqWorkspace();
  const [input, setInput] = useState('');
  const scrollRef = useRef(null);
  const d = isDayMode;

  const messages = task.messages || [];
  const historicalTasks = useMemo(
    () => (sessionTasks || []).filter((sessionTask) => sessionTask.id !== task.id),
    [sessionTasks, task.id]
  );
  const userMessages = useMemo(() => messages.filter((msg) => msg.role === 'user'), [messages]);
  const agentMessages = useMemo(() => messages.filter((msg) => msg.role === 'agent'), [messages]);
  const finalAnswer = String(task.finalAnswer || '').trim();
  const [expandedAgents, setExpandedAgents] = useState({});
  const [renderedAgentMessages, setRenderedAgentMessages] = useState([]);
  const [typingState, setTypingState] = useState(null);
  const pendingQueueRef = useRef([]);
  const seenIdsRef = useRef(new Set());
  const typingTimerRef = useRef(null);
  const hitlState = task?.hitl || { open: false, questions: [], answers: {}, answerModes: {}, currentIndex: 0 };
  const questions = hitlState.questions || [];
  const currentIndex = Number.isFinite(hitlState.currentIndex) ? hitlState.currentIndex : 0;
  const currentQuestion = questions[currentIndex] || null;
  const currentQuestionId = currentQuestion?.requirement_id || '';
  const currentQuestionAnswer = currentQuestionId ? (hitlState.answers?.[currentQuestionId] || '') : '';
  const currentQuestionMode = currentQuestionId ? (hitlState.answerModes?.[currentQuestionId] || 'option') : 'option';
  const currentQuestionOptions = Array.isArray(currentQuestion?.answer_options) && currentQuestion.answer_options.length > 0
    ? currentQuestion.answer_options
    : quickChips(currentQuestion?.question || '');

  useEffect(() => {
    setExpandedAgents({});
    setRenderedAgentMessages(agentMessages);
    setTypingState(null);
    pendingQueueRef.current = [];
    seenIdsRef.current = new Set(agentMessages.map((msg) => msg.id));
    if (typingTimerRef.current) {
      window.clearTimeout(typingTimerRef.current);
      typingTimerRef.current = null;
    }
  }, [task.id]);

  function handlePollNext() {
    if (!currentQuestionId) return;
    if (!String(currentQuestionAnswer || '').trim()) return;
    if (currentIndex < Math.max(questions.length - 1, 0)) {
      updateHitlIndex(task.id, currentIndex + 1);
      return;
    }
    resume(task.id, 'User answered HITL prompt');
  }

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [userMessages.length, renderedAgentMessages.length, typingState?.text]);

  useEffect(() => {
    const unseen = agentMessages.filter((msg) => !seenIdsRef.current.has(msg.id));
    if (unseen.length > 0) {
      unseen.forEach((msg) => {
        pendingQueueRef.current.push(msg);
        seenIdsRef.current.add(msg.id);
      });
    }
  }, [agentMessages]);

  useEffect(() => {
    if (typingState || pendingQueueRef.current.length === 0) {
      return undefined;
    }

    const next = pendingQueueRef.current.shift();
    const content = String(next.content || '');
    const isStrategic = next.agent === 'BLAIQ-CORE' || next.agent === 'Strategic Planner';
    const step = isStrategic ? 1 : 3;
    const delay = isStrategic ? 10 : 4;   // reduced from 18/8 for faster streaming
    const startDelay = isStrategic ? 90 : 25;  // reduced from 180/50 for faster initial display

    setTypingState({
      id: next.id,
      agent: next.agent || 'System',
      at: next.at,
      source: next,
      text: '',
      fullText: content,
      step,
      delay,
    });
    return undefined;
  }, [typingState, agentMessages.length]);

  useEffect(() => {
    if (!typingState) {
      return undefined;
    }

    const fullText = String(typingState.fullText || '');
    const currentText = String(typingState.text || '');
    const nextLength = Math.min(fullText.length, currentText.length + Number(typingState.step || 1));
    const nextText = fullText.slice(0, nextLength);
    const isComplete = nextLength >= fullText.length;
    const wait = currentText.length === 0
      ? (typingState.agent === 'BLAIQ-CORE' || typingState.agent === 'Strategic Planner' ? 90 : 25)  // reduced from 180/50
      : Number(typingState.delay || 12);

    typingTimerRef.current = window.setTimeout(() => {
      if (isComplete) {
        setRenderedAgentMessages((prev) => [...prev, { ...typingState.source, content: fullText }]);
        setTypingState(null);
        typingTimerRef.current = null;
        return;
      }
      setTypingState((prev) => prev ? { ...prev, text: nextText } : prev);
      typingTimerRef.current = null;
    }, wait);

    return () => {
      if (typingTimerRef.current) {
        window.clearTimeout(typingTimerRef.current);
        typingTimerRef.current = null;
      }
    };
  }, [typingState]);

  useEffect(() => () => {
    if (typingTimerRef.current) {
      window.clearTimeout(typingTimerRef.current);
      typingTimerRef.current = null;
    }
  }, []);

  const streams = useMemo(() => {
    const visibleMessages = typingState?.source && String(typingState?.text || '').trim()
      ? [...renderedAgentMessages, { ...typingState.source, content: typingState.text }]
      : renderedAgentMessages;
    return buildAgentStreams(visibleMessages);
  }, [renderedAgentMessages, typingState]);

  const hitlVisible = useMemo(() => {
    if (!(hitlState.open && currentQuestion)) {
      return false;
    }
    return streams.some((stream) => stream.agent === 'HITL Agent' && stream.entries.length > 0);
  }, [currentQuestion, hitlState.open, streams]);

  function toggleAgent(agent) {
    setExpandedAgents((prev) => ({
      ...prev,
      [agent]: !prev[agent],
    }));
  }

  function handleSend(e) {
    e?.preventDefault();
    if (!input.trim()) return;
    submit(input.trim());
    setInput('');
  }

  async function handleStop() {
    if (task?.threadId) {
      try {
        await cancelWorkflow(task.threadId);
      } catch (err) {
        console.error('Failed to stop workflow:', err);
      }
    }
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Top bar */}
      <div className={`flex items-center justify-between border-b px-5 py-3 ${d ? 'border-gray-100' : 'border-[#1e1e1e]'}`}>
        <div className="flex items-center gap-2">
          {task.currentAgent && task.status === 'running' && (
            <span className="flex items-center gap-1.5 text-[12px] text-blue-500">
              <Loader2 size={12} className="animate-spin" /> {task.currentAgent}
            </span>
          )}
          {task.status === 'complete' && (
            <span className="flex items-center gap-1.5 text-[12px] text-emerald-500">
              <CheckCircle size={12} /> Complete
            </span>
          )}
          {!task.currentAgent && task.status === 'running' && (
            <span className={`text-[12px] ${d ? 'text-gray-400' : 'text-[#525252]'}`}>Processing...</span>
          )}
        </div>
        {!previewOpen && (
          <button
            type="button"
            onClick={() => setPreviewOpen(true)}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11px] font-medium transition-colors ${
              d ? 'text-gray-500 hover:bg-gray-50 hover:text-gray-700' : 'text-[#525252] hover:bg-[#1a1a1a] hover:text-[#a1a1a1]'
            }`}
          >
            <Eye size={12} /> Show panel
          </button>
        )}
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-6">
        <div className="mx-auto max-w-3xl space-y-5">
          {historicalTasks.map((historicalTask) => {
            const historicalMessages = historicalTask.messages || [];
            const historicalUsers = historicalMessages.filter((msg) => msg.role === 'user');
            const historicalAgents = buildAgentStreams(historicalMessages.filter((msg) => msg.role === 'agent'));
            const historicalAnswer = String(historicalTask.finalAnswer || '').trim();
            return (
              <div key={historicalTask.id} className="space-y-5 border-b border-black/5 pb-5 last:border-b-0">
                {historicalUsers.length > 0 ? (
                  <div className="pb-2">
                    <div className="mb-3 flex items-center gap-2">
                      <div className={`flex h-8 w-8 items-center justify-center rounded-full ${d ? 'bg-gray-900 text-white' : 'bg-white text-black'}`}>
                        <User size={14} />
                      </div>
                      <div>
                        <div className={`text-[12px] font-semibold ${d ? 'text-gray-900' : 'text-white'}`}>You</div>
                        <div className={`text-[10px] ${d ? 'text-gray-400' : 'text-[#5b5b5b]'}`}>Turn brief</div>
                      </div>
                    </div>
                    <div className="space-y-2 pl-10">
                      {historicalUsers.map((msg) => (
                        <div key={msg.id} className={`text-[14px] leading-relaxed ${d ? 'text-gray-900' : 'text-white'}`}>
                          {msg.content}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}

                {historicalAgents.map((stream) => (
                  <AgentStreamRow
                    key={`${historicalTask.id}-${stream.agent}`}
                    agent={stream.agent}
                    entries={stream.entries}
                    isDayMode={d}
                    active={false}
                    expanded={Boolean(expandedAgents[`${historicalTask.id}:${stream.agent}`])}
                    onToggle={() => toggleAgent(`${historicalTask.id}:${stream.agent}`)}
                    visibleText={stream.entries[stream.entries.length - 1]?.content || ''}
                  />
                ))}

                {historicalAnswer ? (
                  <FinalAnswerCard
                    taskId={historicalTask.id}
                    content={historicalAnswer}
                    isDayMode={d}
                    hypothesisTree={historicalTask.evidencePack?.metadata?.hypothesis_tree}
                    hasStreamed={historicalTask.finalAnswerStreamed !== false}
                    onStreamComplete={markFinalAnswerStreamed}
                  />
                ) : null}
              </div>
            );
          })}

          {userMessages.length > 0 ? (
            <div className="pb-4">
              <div className="mb-3 flex items-center gap-2">
                <div className={`flex h-8 w-8 items-center justify-center rounded-full ${d ? 'bg-gray-900 text-white' : 'bg-white text-black'}`}>
                  <User size={14} />
                </div>
                <div>
                  <div className={`text-[12px] font-semibold ${d ? 'text-gray-900' : 'text-white'}`}>You</div>
                  <div className={`text-[10px] ${d ? 'text-gray-400' : 'text-[#5b5b5b]'}`}>Task brief</div>
                </div>
              </div>
              <div className="space-y-2 pl-10">
                {userMessages.map((msg) => (
                  <div key={msg.id} className={`text-[14px] leading-relaxed ${d ? 'text-gray-900' : 'text-white'}`}>
                    {msg.content}
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {streams.map((stream) => (
            <AgentStreamRow
              key={stream.agent}
              agent={stream.agent}
              entries={stream.entries}
              isDayMode={d}
              active={task.status === 'running' && task.currentAgent === stream.agent}
              expanded={Boolean(expandedAgents[stream.agent])}
              onToggle={() => toggleAgent(stream.agent)}
              visibleText={stream.entries[stream.entries.length - 1]?.content || ''}
            />
          ))}

          {finalAnswer && task.status === 'complete' && !typingState && pendingQueueRef.current.length === 0 ? (
            <>
              <FinalAnswerCard
                taskId={task.id}
                content={finalAnswer}
                isDayMode={d}
                hypothesisTree={task.evidencePack?.metadata?.hypothesis_tree}
                hasStreamed={task.finalAnswerStreamed === true || task.finalAnswerStreamed === undefined}
                onStreamComplete={markFinalAnswerStreamed}
              />
              {task.evidencePack?.analysis_result && (
                <DataAnalysisResults
                  analysisResult={task.evidencePack.analysis_result}
                  isDayMode={d}
                />
              )}
            </>
          ) : null}
        </div>
      </div>

      {/* Input */}
      <div className={`border-t px-6 py-4 ${d ? 'border-gray-100' : 'border-[#1e1e1e]'}`}>
        <div className="mx-auto max-w-2xl">
          <AnimatePresence mode="wait">
            {hitlVisible && (
              <motion.div
                key={currentQuestionId || 'hitl'}
                initial={{ opacity: 0, y: 18 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 12 }}
                transition={{ duration: 0.24, ease: 'easeOut' }}
                className={`mb-3 overflow-hidden rounded-2xl border shadow-sm ${d ? 'border-blue-100 bg-[#f8fbff]' : 'border-[#2a2a2a] bg-[#111827]'}`}
              >
                <div className="px-4 py-4">
                  <AnimatePresence mode="wait">
                    <motion.div
                      key={currentQuestionId || currentQuestion.question}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -8 }}
                      transition={{ duration: 0.2, ease: 'easeOut' }}
                      className="space-y-3"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className={`text-[11px] font-mono uppercase tracking-[0.12em] ${d ? 'text-gray-400' : 'text-[#a1a1a1]'}`}>
                          Question {currentIndex + 1} / {questions.length || 1}
                        </div>
                        {questions.length > 1 ? (
                          <div className={`text-[11px] font-mono uppercase tracking-[0.12em] ${d ? 'text-gray-400' : 'text-[#a1a1a1]'}`}>
                            {Math.round(((currentIndex + 1) / questions.length) * 100)}%
                          </div>
                        ) : null}
                      </div>

                      <div>
                        <div className={`text-[13px] font-semibold leading-snug ${d ? 'text-gray-900' : 'text-white'}`}>
                          {currentQuestion.question}
                        </div>
                        {currentQuestion.why_it_matters ? (
                          <div className={`mt-1 text-[12px] leading-relaxed ${d ? 'text-gray-600' : 'text-[#a1a1a1]'}`}>
                            {currentQuestion.why_it_matters}
                          </div>
                        ) : null}
                      </div>

                      <div className="flex flex-wrap gap-2">
                        {currentQuestionOptions.map((option) => {
                          const selected = currentQuestionMode === 'option' && currentQuestionAnswer === option;
                          return (
                            <button
                              key={option}
                              type="button"
                              onClick={() => {
                                updateHitlAnswer(task.id, currentQuestionId, option);
                                updateHitlAnswerMode(task.id, currentQuestionId, 'option');
                              }}
                              className={`rounded-full border px-3 py-1.5 text-[12px] transition-colors ${
                                selected
                                  ? 'border-blue-500 bg-blue-500 text-white'
                                  : d
                                    ? 'border-gray-200 bg-white text-gray-700 hover:border-blue-200 hover:text-blue-600'
                                    : 'border-[#2a2a2a] bg-[#111827] text-[#d4d4d4] hover:border-blue-500 hover:text-white'
                              }`}
                            >
                              {option}
                            </button>
                          );
                        })}
                        <button
                          type="button"
                          onClick={() => updateHitlAnswerMode(task.id, currentQuestionId, 'custom')}
                          className={`rounded-full border px-3 py-1.5 text-[12px] transition-colors ${
                            currentQuestionMode === 'custom'
                              ? 'border-blue-500 bg-blue-500 text-white'
                              : d
                                ? 'border-gray-200 bg-white text-gray-700 hover:border-blue-200 hover:text-blue-600'
                                : 'border-[#2a2a2a] bg-[#111827] text-[#d4d4d4] hover:border-blue-500 hover:text-white'
                          }`}
                        >
                          Type something else
                        </button>
                      </div>

                      <AnimatePresence mode="wait">
                        {currentQuestionMode === 'custom' ? (
                          <motion.div
                            key="custom-answer"
                            initial={{ opacity: 0, y: 8 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: -8 }}
                          >
                            <textarea
                              value={currentQuestionAnswer}
                              onChange={(e) => updateHitlAnswer(task.id, currentQuestionId, e.target.value)}
                              rows={3}
                              placeholder="Type your answer here..."
                              className={`w-full resize-none rounded-xl border px-3 py-2.5 text-[13px] outline-none ${
                                d
                                  ? 'border-gray-200 bg-white text-gray-900 placeholder-gray-400 focus:border-blue-300'
                                  : 'border-[#2a2a2a] bg-[#0f172a] text-white placeholder-[#525252] focus:border-blue-500'
                              }`}
                            />
                          </motion.div>
                        ) : null}
                      </AnimatePresence>

                      <div className="flex items-center justify-between gap-3 border-t border-opacity-40 pt-3" style={{ borderColor: d ? '#dbeafe' : '#2a2a2a' }}>
                        <div className={`text-[11px] ${d ? 'text-gray-500' : 'text-[#a1a1a1]'}`}>
                          {currentQuestionMode === 'custom' ? 'Type a response or pick an option.' : 'Select an option or switch to custom input.'}
                        </div>
                        <button
                          type="button"
                          onClick={handlePollNext}
                          disabled={!String(currentQuestionAnswer || '').trim()}
                          className={`rounded-lg px-4 py-2 text-[12px] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                            d ? 'bg-gray-900 text-white hover:bg-gray-700' : 'bg-white text-black hover:bg-gray-200'
                          }`}
                        >
                          {currentIndex < Math.max(questions.length - 1, 0) ? 'Next' : 'Continue'}
                        </button>
                      </div>
                    </motion.div>
                  </AnimatePresence>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

        <form onSubmit={handleSend} className="mx-auto max-w-2xl">
          <div className={`flex items-center gap-2 rounded-xl border px-4 py-2.5 shadow-sm transition-all focus-within:ring-2 ${
            d ? 'border-gray-200 bg-white focus-within:ring-blue-100' : 'border-[#2a2a2a] bg-[#141414] focus-within:ring-blue-900/30'
          }`}>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Send a message..."
              className={`flex-1 border-0 bg-transparent text-[14px] outline-none ${d ? 'text-gray-900 placeholder-gray-400' : 'text-white placeholder-[#525252]'}`}
              disabled={isSubmitting}
            />
            {isSubmitting ? (
              <button
                type="button"
                onClick={handleStop}
                className={`flex h-7 w-7 items-center justify-center rounded-lg transition-colors ${
                  d ? 'bg-red-600 text-white hover:bg-red-700' : 'bg-red-500 text-white hover:bg-red-600'
                }`}
                title="Stop workflow"
              >
                <Square size={12} />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!input.trim()}
                className={`flex h-7 w-7 items-center justify-center rounded-lg transition-colors ${
                  d ? 'bg-gray-900 text-white hover:bg-gray-700 disabled:bg-gray-200 disabled:text-gray-400'
                    : 'bg-white text-black hover:bg-gray-200 disabled:bg-[#1e1e1e] disabled:text-[#525252]'
                }`}
              >
                <ArrowUp size={12} />
              </button>
            )}
          </div>
        </form>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   EMPTY STATE — "What can I do for you?"
   ═══════════════════════════════════════════════════════════════════════════ */

function EmptyState({ onSubmit, query, setQuery, isSubmitting }) {
  const inputRef = useRef(null);
  const fileRef = useRef(null);
  const { isDayMode } = useBlaiqWorkspace();
  const [analysisMode, setAnalysisMode] = useState('standard'); // 'standard' | 'deep_research' | 'finance' | 'data_science'
  const d = isDayMode;

  const modeDescriptions = {
    standard: { label: 'Fast recall', description: 'HIVE-MIND memory only', icon: Zap },
    deep_research: { label: 'Deep research', description: 'Full decomposition tree', icon: Brain },
    finance: { label: 'Finance analysis', description: 'Hypothesis-driven research', icon: BarChart3 },
    data_science: { label: 'Data analysis', description: 'Code execution & stats', icon: FileUp },
  };

  function handleSubmit(e) {
    e?.preventDefault();
    if (query.trim()) onSubmit(query.trim(), 'hybrid', analysisMode);
  }

  async function handleFileUpload(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      await uploadFile(file, 'default', null);
      setQuery((prev) => prev ? `${prev} (uploaded: ${file.name})` : `Analyze ${file.name}`);
    } catch { /* ignore */ }
  }

  const quickActions = [
    { icon: Sparkles, label: 'Create slides', hint: 'Create a professional pitch deck presentation' },
    { icon: Globe, label: 'Build website', hint: 'Design a modern landing page' },
    { icon: Search, label: 'Research', hint: 'Quick HIVE-MIND recall', onClick: () => setAnalysisMode('standard') },
    { icon: Brain, label: 'Deep Research', hint: 'Full decomposition tree analysis', onClick: () => setAnalysisMode('deep_research') },
    { icon: BarChart3, label: 'Analyze data', hint: 'Upload and analyze CSV, Excel, or JSON data files', onClick: () => setAnalysisMode('data_science') },
    { icon: FileUp, label: 'Analyze document', hint: 'Analyze the uploaded document and create a summary' },
  ];

  return (
    <div className={`flex h-full flex-col items-center justify-center px-6 ${d ? '' : 'bg-[#0a0a0a]'}`}>
      <div className="w-full max-w-2xl">
        <h1 className={`mb-10 text-center text-[32px] font-semibold ${d ? 'text-gray-900' : 'text-white'}`}>
          What can I do for you?
        </h1>

        <form onSubmit={handleSubmit}>
          <div className={`overflow-hidden rounded-2xl border shadow-sm transition-all focus-within:shadow-md focus-within:ring-2 ${
            d ? 'border-gray-200 bg-white focus-within:ring-blue-100' : 'border-[#2a2a2a] bg-[#141414] focus-within:ring-blue-900/30'
          }`}>
            <textarea
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSubmit(); } }}
              placeholder="Assign a task or ask anything"
              className={`w-full resize-none border-0 bg-transparent px-5 pt-5 pb-2 text-[15px] outline-none ${
                d ? 'text-gray-900 placeholder-gray-400' : 'text-white placeholder-[#525252]'
              }`}
              rows={3}
              disabled={isSubmitting}
            />

            {/* Analysis Mode Selector */}
            <div className={`mx-5 mb-3 flex flex-col gap-2 rounded-lg border px-3 py-3 ${
              d ? 'border-gray-200 bg-gray-50 text-gray-700' : 'border-[#2a2a2a] bg-[#1e1e1e] text-[#a1a1a1]'
            }`}>
              <div className="flex items-center gap-2">
                <BookOpen size={14} className={d ? 'text-gray-500' : 'text-[#525252]'} />
                <span className={`text-[13px] ${d ? 'text-gray-600' : 'text-[#8a8a8a]'}`}>Analysis Mode:</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => setAnalysisMode('standard')}
                  className={`flex items-center gap-2 rounded-md px-3 py-2 transition-all ${
                    analysisMode === 'standard'
                      ? d ? 'bg-white text-gray-900 shadow-sm ring-1 ring-gray-200' : 'bg-[#2a2a2a] text-white ring-1 ring-[#3a3a3a]'
                      : d ? 'bg-gray-100 text-gray-600 hover:bg-gray-200' : 'bg-[#252525] text-[#8a8a8a] hover:bg-[#2a2a2a]'
                  }`}
                >
                  <Zap size={14} className={analysisMode === 'standard' ? 'text-amber-500' : d ? 'text-gray-400' : 'text-[#525252]'} />
                  <div className="flex flex-col items-start">
                    <span className="text-[12px] font-medium">Standard</span>
                    <span className={`text-[10px] ${analysisMode === 'standard' ? (d ? 'text-gray-500' : 'text-[#a1a1a1]') : (d ? 'text-gray-400' : 'text-[#525252]')}`}>Fast recall</span>
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() => setAnalysisMode('deep_research')}
                  className={`flex items-center gap-2 rounded-md px-3 py-2 transition-all ${
                    analysisMode === 'deep_research'
                      ? d ? 'bg-white text-gray-900 shadow-sm ring-1 ring-gray-200' : 'bg-[#2a2a2a] text-white ring-1 ring-[#3a3a3a]'
                      : d ? 'bg-gray-100 text-gray-600 hover:bg-gray-200' : 'bg-[#252525] text-[#8a8a8a] hover:bg-[#2a2a2a]'
                  }`}
                >
                  <Brain size={14} className={analysisMode === 'deep_research' ? 'text-purple-500' : d ? 'text-gray-400' : 'text-[#525252]'} />
                  <div className="flex flex-col items-start">
                    <span className="text-[12px] font-medium">Deep Research</span>
                    <span className={`text-[10px] ${analysisMode === 'deep_research' ? (d ? 'text-gray-500' : 'text-[#a1a1a1]') : (d ? 'text-gray-400' : 'text-[#525252]')}`}>Full tree</span>
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() => setAnalysisMode('finance')}
                  className={`flex items-center gap-2 rounded-md px-3 py-2 transition-all ${
                    analysisMode === 'finance'
                      ? d ? 'bg-white text-gray-900 shadow-sm ring-1 ring-gray-200' : 'bg-[#2a2a2a] text-white ring-1 ring-[#3a3a3a]'
                      : d ? 'bg-gray-100 text-gray-600 hover:bg-gray-200' : 'bg-[#252525] text-[#8a8a8a] hover:bg-[#2a2a2a]'
                  }`}
                >
                  <BarChart3 size={14} className={analysisMode === 'finance' ? 'text-emerald-500' : d ? 'text-gray-400' : 'text-[#525252]'} />
                  <div className="flex flex-col items-start">
                    <span className="text-[12px] font-medium">Finance</span>
                    <span className={`text-[10px] ${analysisMode === 'finance' ? (d ? 'text-gray-500' : 'text-[#a1a1a1]') : (d ? 'text-gray-400' : 'text-[#525252]')}`}>Hypothesis-driven</span>
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() => setAnalysisMode('data_science')}
                  className={`flex items-center gap-2 rounded-md px-3 py-2 transition-all ${
                    analysisMode === 'data_science'
                      ? d ? 'bg-white text-gray-900 shadow-sm ring-1 ring-gray-200' : 'bg-[#2a2a2a] text-white ring-1 ring-[#3a3a3a]'
                      : d ? 'bg-gray-100 text-gray-600 hover:bg-gray-200' : 'bg-[#252525] text-[#8a8a8a] hover:bg-[#2a2a2a]'
                  }`}
                >
                  <FileUp size={14} className={analysisMode === 'data_science' ? 'text-blue-500' : d ? 'text-gray-400' : 'text-[#525252]'} />
                  <div className="flex flex-col items-start">
                    <span className="text-[12px] font-medium">Data</span>
                    <span className={`text-[10px] ${analysisMode === 'data_science' ? (d ? 'text-gray-500' : 'text-[#a1a1a1]') : (d ? 'text-gray-400' : 'text-[#525252]')}`}>Code execution</span>
                  </div>
                </button>
              </div>
              {/* Mode description banner */}
              <div className={`mt-1 flex items-center gap-2 rounded-md px-2 py-1.5 text-[11px] ${
                d ? 'bg-blue-50 text-blue-700' : 'bg-[#1a1a2e] text-blue-300'
              }`}>
                {React.createElement(modeDescriptions[analysisMode].icon, { size: 12 })}
                <span>
                  <strong>{modeDescriptions[analysisMode].label}</strong> — {modeDescriptions[analysisMode].description}
                </span>
              </div>
            </div>
            <div className="flex items-center justify-between px-4 pb-3">
              <div className="flex items-center gap-0.5">
                <button type="button" onClick={() => fileRef.current?.click()} className={`rounded-lg p-2 ${d ? 'text-gray-400 hover:bg-gray-100' : 'text-[#525252] hover:bg-[#1e1e1e]'}`}>
                  <Paperclip size={16} />
                </button>
                <button type="button" className={`rounded-lg p-2 ${d ? 'text-gray-400 hover:bg-gray-100' : 'text-[#525252] hover:bg-[#1e1e1e]'}`}>
                  <Globe size={16} />
                </button>
                <button type="button" className={`rounded-lg p-2 ${d ? 'text-gray-400 hover:bg-gray-100' : 'text-[#525252] hover:bg-[#1e1e1e]'}`}>
                  <MessageSquare size={16} />
                </button>
              </div>
              <button
                type="submit"
                disabled={!query.trim() || isSubmitting}
                className={`flex h-8 w-8 items-center justify-center rounded-lg ${
                  d ? 'bg-gray-900 text-white hover:bg-gray-700 disabled:bg-gray-200 disabled:text-gray-400'
                    : 'bg-white text-black hover:bg-gray-200 disabled:bg-[#1e1e1e] disabled:text-[#525252]'
                }`}
              >
                {isSubmitting ? <Loader2 size={14} className="animate-spin" /> : <ArrowUp size={14} />}
              </button>
            </div>
          </div>
          <input ref={fileRef} type="file" className="hidden" onChange={handleFileUpload} />
        </form>

        <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
          {quickActions.map((a) => (
            <button
              key={a.label}
              type="button"
              onClick={() => {
                if (a.onClick) a.onClick();
                setQuery(a.hint);
              }}
              className={`flex items-center gap-2 rounded-full border px-4 py-2 text-[13px] transition-all ${
                d ? 'border-gray-200 bg-white text-gray-600 hover:border-gray-300 hover:bg-gray-50'
                  : 'border-[#2a2a2a] bg-[#141414] text-[#a1a1a1] hover:border-[#3a3a3a] hover:bg-[#1e1e1e]'
              }`}
            >
              <a.icon size={14} /> {a.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   ACTIVE TASK VIEW — Center (conversation) + Right (steps + preview)
   ═══════════════════════════════════════════════════════════════════════════ */

function ActiveTaskView({ task, sessionTasks }) {
  const { previewOpen, setPreviewOpen } = useBlaiqWorkspace();
  const [panelWidth, setPanelWidth] = useState(380);
  const draggingRef = useRef(false);

  // Auto-open right panel on first event
  useEffect(() => {
    if (task.events.length > 0 && !previewOpen) setPreviewOpen(true);
  }, [task.events.length]);

  const onResizeStart = useCallback((e) => {
    e.preventDefault();
    draggingRef.current = true;
    const startX = e.clientX;
    const startWidth = panelWidth;

    const onMove = (me) => {
      const delta = startX - me.clientX;
      setPanelWidth(Math.max(280, Math.min(800, startWidth + delta)));
    };
    const onUp = () => {
      draggingRef.current = false;
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }, [panelWidth]);

  return (
    <div className="flex h-full flex-1 overflow-hidden bg-[#f3efe7]">
      {/* Center — conversation */}
      <ConversationArea task={task} sessionTasks={sessionTasks} />

      {/* Right — resizable steps + preview panel */}
      {previewOpen && (
        <>
          {/* Drag handle */}
          <div
            className="flex w-2 shrink-0 cursor-col-resize items-center justify-center hover:bg-gray-200/50 dark:hover:bg-[#2a2a2a] transition-colors"
            onMouseDown={onResizeStart}
          >
            <div className="h-8 w-0.5 rounded-full bg-gray-300 dark:bg-[#3a3a3a]" />
          </div>
          <div
            className="flex-shrink-0 border-l border-gray-100 dark:border-[#1e1e1e]"
            style={{ width: panelWidth }}
          >
            <RightPanel task={task} onClose={() => setPreviewOpen(false)} />
          </div>
        </>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   MAIN
   ═══════════════════════════════════════════════════════════════════════════ */

export default function Chat() {
  const { activeTask, sessionTasks, sessionId, switchSession, query, setQuery, submit, isSubmitting } = useBlaiqWorkspace();
  const [selectedModel, setSelectedModel] = useState('sonnet-4.5');
  const [selectedMode, setSelectedMode] = useState('standard');
  const navigate = useNavigate();
  const params = useParams();
  const routeSessionId = params.sessionId;

  useEffect(() => {
    if (routeSessionId && routeSessionId !== sessionId) {
      switchSession(routeSessionId);
      return;
    }
    if (!routeSessionId && sessionId) {
      navigate(`/app/chat/${sessionId}`, { replace: true });
    }
  }, [navigate, routeSessionId, sessionId, switchSession]);

  const handleSend = useCallback((message, source = 'hybrid', analysisMode = 'standard') => {
    setQuery(message);
    submit(message, source, analysisMode);
  }, [setQuery, submit]);

  if (!activeTask && (!sessionTasks || sessionTasks.length === 0)) {
    return (
      <div className="h-full bg-[#f3efe7]">
        <BoltStyleChat
          onSend={handleSend}
          selectedModel={selectedModel}
          selectedMode={selectedMode}
          onModelChange={setSelectedModel}
          onModeChange={setSelectedMode}
        />
      </div>
    );
  }

  const visibleTask = activeTask || sessionTasks[sessionTasks.length - 1] || null;
  if (!visibleTask) {
    return null;
  }

  return <ActiveTaskView task={visibleTask} sessionTasks={sessionTasks} />;
}
