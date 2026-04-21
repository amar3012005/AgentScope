import React, { useEffect, useMemo, useRef, useState } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  ArrowUp,
  Bot,
  BrainCircuit,
  BookOpen,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Eye,
  FileText,
  FileCog,
  GitBranch,
  Loader2,
  MapPin,
  Mic,
  Navigation,
  Paperclip,
  PanelRight,
  Search,
  ShieldCheck,
  Sparkles,
  Users,
  Zap,
} from 'lucide-react';
import {
  buildWorkflowPlanFromRouting,
  useBlaiqWorkspace,
  normalizePreviewHtml,
  quickChips,
} from '../shared/blaiq-workspace-context';

/* ─── Tabs for the right rail (active conversation) ────────────────────────── */

const tabs = [
  { id: 'preview', label: 'Preview', icon: PanelRight },
  { id: 'plan', label: 'Plan', icon: GitBranch },
  { id: 'schema', label: 'Schema', icon: FileCog },
  { id: 'governance', label: 'Governance', icon: ShieldCheck },
];

/* ─── Response Parser — splits into thinking / answer / sources ────────────── */

function parseAssistantResponse(content) {
  if (!content || typeof content !== 'string') return { thinking: '', answer: content || '', sources: [], confidence: null };

  let thinking = '';
  let answer = '';
  let sourcesRaw = '';
  let confidenceBlock = '';

  // Extract ANALYSIS / thinking section (before **ANSWER**: or ## Core or first ## heading after ---)
  const analysisMatch = content.match(/^([\s\S]*?)(?:\*\*ANSWER\*\*:|---\s*\n\s*\*\*ANSWER)/m);
  if (analysisMatch) {
    thinking = analysisMatch[1].replace(/^#+\s*(ANALYSIS|Final Answer)\s*/gim, '').trim();
  }

  // Extract answer section
  const answerMatch = content.match(/\*\*ANSWER\*\*:\s*([\s\S]*?)(?=\n## (?:Confidence|Sources|Context)\b|\*\*CONTEXT\*\*:)/i);
  if (answerMatch) {
    answer = answerMatch[1].trim();
  } else {
    // Fallback: everything after ANSWER or after the --- separator
    const afterAnswer = content.match(/\*\*ANSWER\*\*:\s*([\s\S]*)/i);
    if (afterAnswer) {
      answer = afterAnswer[1].trim();
    } else {
      // No ANALYSIS/ANSWER structure — the whole thing is the answer
      answer = content;
      thinking = '';
    }
  }

  // Extract confidence
  const confMatch = content.match(/## Confidence\s*([\s\S]*?)(?=\n## |\n\*\*|$)/i);
  if (confMatch) {
    confidenceBlock = confMatch[1].trim();
    // Remove confidence from answer if it leaked in
    answer = answer.replace(/## Confidence[\s\S]*?(?=\n## Sources|\n## Context|$)/i, '').trim();
  }

  // Extract sources
  const sourcesMatch = content.match(/## Sources\s*\(GraphRAG\)\s*([\s\S]*?)$/i)
    || content.match(/## Sources\s*([\s\S]*?)$/i);
  if (sourcesMatch) {
    sourcesRaw = sourcesMatch[1].trim();
    // Remove sources from answer if it leaked in
    answer = answer.replace(/## Sources[\s\S]*$/i, '').trim();
  }

  // Remove CONTEXT section from answer
  answer = answer.replace(/\*\*CONTEXT\*\*:\s*[\s\S]*?(?=\n## |$)/i, '').trim();
  answer = answer.replace(/## Context[\s\S]*?(?=\n## Sources|$)/i, '').trim();

  // Parse individual sources
  const sources = sourcesRaw
    .split('\n')
    .map((line) => line.replace(/^[-•*]\s*/, '').trim())
    .filter((line) => line.startsWith('[GraphRAG]') || line.startsWith('[Source'))
    .map((line) => {
      const srcMatch = line.match(/\[Source:\s*(.+?)(?:,\s*p\.\s*(.+?))?\]/);
      if (srcMatch) return { file: srcMatch[1].trim(), page: srcMatch[2]?.trim() || '' };
      const altMatch = line.match(/\[GraphRAG\]\s*\[Source:\s*(.+?)(?:,\s*p\.\s*(.+?))?\]/);
      if (altMatch) return { file: altMatch[1].trim(), page: altMatch[2]?.trim() || '' };
      return { file: line.replace(/^\[GraphRAG\]\s*/, ''), page: '' };
    });

  // Parse confidence score
  let confidence = null;
  if (confidenceBlock) {
    const scoreMatch = confidenceBlock.match(/Score:\s*([\d.]+)/i);
    const chunksMatch = confidenceBlock.match(/Evidence Chunks:\s*(\d+)/i);
    const docsMatch = confidenceBlock.match(/Source Documents:\s*(\d+)/i);
    confidence = {
      score: scoreMatch ? parseFloat(scoreMatch[1]) : null,
      chunks: chunksMatch ? parseInt(chunksMatch[1], 10) : null,
      docs: docsMatch ? parseInt(docsMatch[1], 10) : null,
    };
  }

  return { thinking, answer, sources, confidence };
}

/* ─── Markdown rendering config ────────────────────────────────────────────── */

const mdComponents = {
  h1: ({ children }) => <h1 className="mb-3 mt-5 text-[20px] font-bold text-[#F6F4F1] first:mt-0">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-2 mt-4 text-[17px] font-bold text-[#F6F4F1] first:mt-0">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-2 mt-3 text-[15px] font-semibold text-[#F6F4F1]">{children}</h3>,
  h4: ({ children }) => <h4 className="mb-1 mt-2 text-[14px] font-semibold text-[#E4DED2]">{children}</h4>,
  p: ({ children }) => <p className="mb-3 text-[14px] leading-[1.75] text-[#b8b0a8] last:mb-0">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-[#E4DED2]">{children}</strong>,
  em: ({ children }) => <em className="text-[#9a9a9a]">{children}</em>,
  ul: ({ children }) => <ul className="mb-3 ml-1 space-y-1 text-[14px] text-[#a1a1a1]">{children}</ul>,
  ol: ({ children }) => <ol className="mb-3 ml-1 list-decimal space-y-1 pl-4 text-[14px] text-[#a1a1a1]">{children}</ol>,
  li: ({ children }) => (
    <li className="flex gap-2 leading-[1.7]">
      <span className="mt-[10px] h-1 w-1 flex-shrink-0 rounded-full bg-[#525252]" />
      <span>{children}</span>
    </li>
  ),
  a: ({ href, children }) => <a href={href} className="text-[#3b82f6] underline decoration-[#3b82f6]/30 hover:decoration-[#3b82f6]" target="_blank" rel="noopener noreferrer">{children}</a>,
  code: ({ children, className }) => {
    const isBlock = className?.includes('language-');
    if (isBlock) {
      return <code className="block overflow-x-auto rounded-lg bg-[#0a0a0a] p-3 text-[13px] text-[#d4d4d4]">{children}</code>;
    }
    return <code className="rounded-md bg-[#1a1a1a] px-1.5 py-0.5 text-[13px] text-[#d4d4d4]">{children}</code>;
  },
  pre: ({ children }) => <pre className="mb-3 overflow-x-auto rounded-lg bg-[#0a0a0a] text-[13px]">{children}</pre>,
  blockquote: ({ children }) => <blockquote className="mb-3 border-l-2 border-[#333] pl-4 text-[#6b6b6b]">{children}</blockquote>,
  hr: () => <hr className="my-4 border-[#1e1e1e]" />,
  table: ({ children }) => (
    <div className="mb-3 overflow-x-auto rounded-lg border border-[#1e1e1e]">
      <table className="w-full text-[13px]">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-[#141414] text-[#a1a1a1]">{children}</thead>,
  tbody: ({ children }) => <tbody>{children}</tbody>,
  tr: ({ children }) => <tr className="border-b border-[#1e1e1e] last:border-0">{children}</tr>,
  th: ({ children }) => <th className="px-3 py-2 text-left font-semibold text-[#d4d4d4]">{children}</th>,
  td: ({ children }) => <td className="px-3 py-2 text-[#a1a1a1]">{children}</td>,
};

/* ─── Streamed-message cache — once a message has been animated, skip on re-render */

const _streamedIds = new Set();

/* ─── Typewriter hook — streams text char by char at a given speed ──────────── */

const THINKING_CHAR_SPEED = 8;   // ms per char for thinking lines
const ANSWER_CHAR_SPEED = 12;    // ms per char for answer body
const LINE_PAUSE = 120;          // ms pause between thinking lines

function useTypewriter(fullText, charSpeed, { enabled = true, startDelay = 0 } = {}) {
  const [displayed, setDisplayed] = useState('');
  const [done, setDone] = useState(false);
  const rafRef = useRef(null);
  const idxRef = useRef(0);
  const lastRef = useRef(0);

  useEffect(() => {
    if (!enabled || !fullText) { setDisplayed(fullText || ''); setDone(true); return; }
    setDisplayed('');
    setDone(false);
    idxRef.current = 0;
    lastRef.current = 0;

    const timeout = setTimeout(() => {
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
          rafRef.current = requestAnimationFrame(tick);
        } else {
          setDone(true);
        }
      }
      rafRef.current = requestAnimationFrame(tick);
    }, startDelay);

    return () => { clearTimeout(timeout); if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [fullText, charSpeed, enabled, startDelay]);

  return { displayed, done };
}

/* ─── Thinking Stream — shows lines appearing one by one with typewriter ──── */

function ThinkingStream({ content, onComplete }) {
  const lines = useMemo(() => {
    if (!content) return [];
    return content
      .split('\n')
      .map((l) => l.replace(/^\*\*/, '').replace(/\*\*$/, '').trim())
      .filter(Boolean);
  }, [content]);

  const [visibleCount, setVisibleCount] = useState(0);
  const [currentLineText, setCurrentLineText] = useState('');
  const [currentLineDone, setCurrentLineDone] = useState(false);
  const completedRef = useRef(false);

  // Stream one line at a time
  useEffect(() => {
    if (visibleCount >= lines.length) return;
    const line = lines[visibleCount];
    let charIdx = 0;
    setCurrentLineText('');
    setCurrentLineDone(false);

    const interval = setInterval(() => {
      charIdx += 2; // 2 chars per tick for speed
      if (charIdx >= line.length) {
        setCurrentLineText(line);
        setCurrentLineDone(true);
        clearInterval(interval);
        // Pause then advance to next line
        setTimeout(() => {
          setVisibleCount((c) => c + 1);
        }, LINE_PAUSE);
      } else {
        setCurrentLineText(line.slice(0, charIdx));
      }
    }, THINKING_CHAR_SPEED);

    return () => clearInterval(interval);
  }, [visibleCount, lines]);

  // Notify parent when all lines are done
  useEffect(() => {
    if (visibleCount >= lines.length && lines.length > 0 && !completedRef.current) {
      completedRef.current = true;
      onComplete?.();
    }
  }, [visibleCount, lines.length, onComplete]);

  if (!content) return null;

  function renderLine(text, idx) {
    const colonIdx = text.indexOf(':');
    if (colonIdx > 0 && colonIdx < 40) {
      const key = text.slice(0, colonIdx).replace(/\*\*/g, '').trim();
      const val = text.slice(colonIdx + 1).replace(/\*\*/g, '').trim();
      return (
        <div key={idx} className="mb-1.5 flex gap-2 text-[12px]">
          <span className="font-medium text-[#6b6b6b]">{key}:</span>
          <span className="text-[#9a9a9a]">{val}</span>
        </div>
      );
    }
    if (text.startsWith('-') || text.startsWith('•')) {
      return (
        <div key={idx} className="mb-1 flex gap-2 pl-2 text-[12px] text-[#9a9a9a]">
          <span className="mt-[6px] h-1 w-1 flex-shrink-0 rounded-full bg-[#525252]" />
          {text.replace(/^[-•]\s*/, '')}
        </div>
      );
    }
    return <div key={idx} className="mb-1.5 text-[12px] text-[#9a9a9a]">{text}</div>;
  }

  const allDone = visibleCount >= lines.length;

  return (
    <div className="mb-4 rounded-xl border border-[#a855f7]/20 bg-[#0f0f0f] overflow-hidden">
      {/* Header with live indicator */}
      <div className="flex items-center gap-2 border-b border-[#1e1e1e] px-4 py-2.5">
        <div className="flex h-5 w-5 items-center justify-center rounded-md bg-[#a855f7]/15">
          <BrainCircuit size={12} className={`text-[#a855f7] ${!allDone ? 'gps-glow' : ''}`} />
        </div>
        <span className="flex-1 text-[12px] font-semibold text-[#a855f7]">
          {allDone ? 'Analysis complete' : 'Analyzing request...'}
        </span>
        {!allDone && (
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#a855f7] opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-[#a855f7]" />
          </span>
        )}
      </div>

      {/* Streamed lines */}
      <div className="px-4 py-3">
        {/* Already completed lines */}
        {lines.slice(0, visibleCount).map((line, i) => renderLine(line, i))}
        {/* Currently streaming line */}
        {visibleCount < lines.length && (
          <div className="mb-1.5 text-[12px] text-[#9a9a9a]">
            {currentLineText}
            <span className="streaming-cursor" />
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── Thinking Collapsed — shown for already-streamed messages ─────────────── */

function ThinkingCollapsed({ content }) {
  const [expanded, setExpanded] = useState(false);
  if (!content) return null;

  const lines = content.split('\n').map((l) => l.replace(/^\*\*/, '').replace(/\*\*$/, '').trim()).filter(Boolean);

  return (
    <div className="mb-4">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 rounded-xl bg-[#141414] px-4 py-2.5 text-left transition-colors hover:bg-[#1a1a1a]"
      >
        <div className="flex h-5 w-5 items-center justify-center rounded-md bg-[#a855f7]/15">
          <BrainCircuit size={12} className="text-[#a855f7]" />
        </div>
        <span className="flex-1 text-[12px] font-semibold text-[#a855f7]">Analysis complete</span>
        <ChevronDown size={14} className={`text-[#525252] transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`} />
      </button>
      {expanded && (
        <div className="mt-1 rounded-b-xl border border-t-0 border-[#1e1e1e] bg-[#0f0f0f] px-4 py-3">
          {lines.map((line, i) => {
            const colonIdx = line.indexOf(':');
            if (colonIdx > 0 && colonIdx < 40) {
              const key = line.slice(0, colonIdx).replace(/\*\*/g, '').trim();
              const val = line.slice(colonIdx + 1).replace(/\*\*/g, '').trim();
              return (
                <div key={i} className="mb-1.5 flex gap-2 text-[12px] last:mb-0">
                  <span className="font-medium text-[#6b6b6b]">{key}:</span>
                  <span className="text-[#9a9a9a]">{val}</span>
                </div>
              );
            }
            return <div key={i} className="mb-1.5 text-[12px] text-[#9a9a9a]">{line}</div>;
          })}
        </div>
      )}
    </div>
  );
}

/* ─── Confidence Badge ─────────────────────────────────────────────────────── */

function ConfidenceBadge({ confidence, visible }) {
  if (!visible || !confidence?.score) return null;
  const pct = Math.round(confidence.score * 100);
  const color = pct >= 80 ? '#F95C4B' : pct >= 50 ? '#f59e0b' : '#ef4444';
  return (
    <div className="mb-4 flex items-center gap-4 rounded-xl bg-[#141414] px-4 py-2.5 animate-[fadeIn_0.3s_ease-out]">
      <div className="flex items-center gap-2">
        <div className="relative h-7 w-7">
          <svg className="h-7 w-7 -rotate-90" viewBox="0 0 28 28">
            <circle cx="14" cy="14" r="11" fill="none" stroke="#1e1e1e" strokeWidth="2.5" />
            <circle cx="14" cy="14" r="11" fill="none" stroke={color} strokeWidth="2.5"
              strokeLinecap="round"
              strokeDasharray={`${2 * Math.PI * 11}`}
              strokeDashoffset={`${2 * Math.PI * 11 * (1 - pct / 100)}`}
              className="transition-all duration-1000"
            />
          </svg>
          <span className="absolute inset-0 flex items-center justify-center text-[8px] font-bold" style={{ color }}>{pct}%</span>
        </div>
        <span className="text-[12px] font-medium text-[#6b6b6b]">Confidence</span>
      </div>
      {confidence.chunks && (
        <div className="flex items-center gap-1.5 text-[11px] text-[#525252]">
          <FileText size={11} />
          <span>{confidence.chunks} chunks</span>
        </div>
      )}
      {confidence.docs && (
        <div className="flex items-center gap-1.5 text-[11px] text-[#525252]">
          <BookOpen size={11} />
          <span>{confidence.docs} docs</span>
        </div>
      )}
    </div>
  );
}

/* ─── Sources Dropdown ─────────────────────────────────────────────────────── */

function SourcesDropdown({ sources, visible }) {
  const [open, setOpen] = useState(false);

  if (!visible || !sources || sources.length === 0) return null;

  return (
    <div className="mt-4 animate-[fadeIn_0.3s_ease-out]">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 rounded-xl bg-[#141414] px-4 py-3 text-left transition-colors hover:bg-[#1a1a1a]"
      >
        <div className="flex h-5 w-5 items-center justify-center rounded-md bg-[#3b82f6]/15">
          <BookOpen size={12} className="text-[#3b82f6]" />
        </div>
        <span className="flex-1 text-[12px] font-semibold text-[#3b82f6]">
          Sources ({sources.length})
        </span>
        <span className="rounded-md bg-[#3b82f6]/10 px-2 py-0.5 text-[10px] font-mono text-[#3b82f6]">
          GraphRAG
        </span>
        <ChevronDown
          size={14}
          className={`text-[#525252] transition-transform duration-200 ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {open && (
        <div className="mt-1 rounded-b-xl border border-t-0 border-[#1e1e1e] bg-[#0f0f0f] p-2">
          {sources.map((src, i) => (
            <div
              key={`${src.file}-${i}`}
              className="flex items-start gap-3 rounded-lg px-3 py-2 transition-colors hover:bg-[#141414]"
            >
              <div className="mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-md bg-[#1a1a1a] text-[10px] font-bold text-[#525252]">
                {i + 1}
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-[12px] font-medium text-[#a1a1a1]">{src.file}</div>
                {src.page && (
                  <div className="text-[11px] text-[#525252]">p. {src.page}</div>
                )}
              </div>
              <FileText size={12} className="mt-1 flex-shrink-0 text-[#333]" />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ─── Streamed Answer — types out the markdown char by char ─────────────────── */

function StreamedAnswer({ content, enabled, onComplete }) {
  const { displayed, done } = useTypewriter(content, ANSWER_CHAR_SPEED, { enabled });

  useEffect(() => {
    if (done) onComplete?.();
  }, [done, onComplete]);

  return (
    <div className="prose-blaiq">
      <Markdown remarkPlugins={[remarkGfm]} components={mdComponents}>
        {displayed}
      </Markdown>
      {!done && <span className="streaming-cursor" />}
    </div>
  );
}

/* ─── Message bubble ───────────────────────────────────────────────────────── */

function MessageCard({ item }) {
  const { isDayMode: d } = useBlaiqWorkspace();

  if (item.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className={`max-w-[72%] rounded-2xl rounded-br-md px-4 py-3 text-[14px] leading-relaxed ring-1 ring-[#F95C4B]/15 ${d ? 'bg-[#F95C4B]/[0.07] text-[#000]' : 'bg-[#1e1410] text-[#F6F4F1]'}`}>
          {item.content}
        </div>
      </div>
    );
  }

  // System events (routing, evidence, rendering status)
  if (item.role === 'system') {
    return (
      <div className="flex justify-start">
        <div className={`max-w-[86%] rounded-2xl border px-4 py-3 ${d ? 'border-[#E4DED2] bg-white/70' : 'border-[#2a2a2a] bg-[#141414]'}`}>
          <div className="mb-2 flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-full bg-[#ff5c4b]/15">
              <Sparkles size={12} className="text-[#ff5c4b]" />
            </div>
            <span className={`text-xs font-semibold ${d ? 'text-[#000]' : 'text-white'}`}>{item.title}</span>
          </div>
          <div className={`whitespace-pre-wrap text-[14px] leading-relaxed ${d ? 'text-[#525252]' : 'text-[#a1a1a1]'}`}>
            {item.content}
          </div>
        </div>
      </div>
    );
  }

  // Assistant response — parse, then stream thinking → answer → sources
  const parsed = useMemo(() => parseAssistantResponse(item.content), [item.content]);

  // Check if this message was already streamed — if so, skip all animation
  const alreadyStreamed = _streamedIds.has(item.id);
  const [phase, setPhase] = useState(
    alreadyStreamed ? 'done' : parsed.thinking ? 'thinking' : 'answer'
  );

  const handleThinkingComplete = useMemo(
    () => () => setPhase('answer'),
    []
  );

  const handleAnswerComplete = useMemo(
    () => () => {
      setPhase('done');
      _streamedIds.add(item.id);
    },
    [item.id]
  );

  // If no thinking, mark done immediately when answer finishes
  useEffect(() => {
    if (alreadyStreamed && phase !== 'done') setPhase('done');
  }, [alreadyStreamed, phase]);

  return (
    <div className="flex justify-start">
      <div className={`max-w-[90%] w-full rounded-2xl border px-5 py-4 ${d ? 'border-[#E4DED2] bg-white/80 shadow-sm' : 'border-[#1e1e1e] bg-[#0f0f0f]'}`}>
        {/* Header */}
        <div className="mb-3 flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-full bg-[#F95C4B]/15">
            <Bot size={13} className="text-[#F95C4B]" />
          </div>
          <span className={`text-[13px] font-semibold ${d ? 'text-[#000]' : 'text-white'}`}>{item.title || 'BLAIQ'}</span>
          {phase !== 'done' && (
            <span className="relative ml-1 flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#F95C4B] opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-[#F95C4B]" />
            </span>
          )}
        </div>

        {/* Phase 1: Thinking stream (visible, line by line, with cursor) */}
        {parsed.thinking && (
          alreadyStreamed ? (
            /* Already streamed — show collapsed toggle */
            <ThinkingCollapsed content={parsed.thinking} />
          ) : (
            <ThinkingStream content={parsed.thinking} onComplete={handleThinkingComplete} />
          )
        )}

        {/* Phase 2: Confidence badge (appears after thinking completes) */}
        <ConfidenceBadge confidence={parsed.confidence} visible={phase === 'answer' || phase === 'done'} />

        {/* Phase 2/done: Answer — streams first time, static after */}
        {(phase === 'answer' || phase === 'done') && (
          <StreamedAnswer
            content={parsed.answer}
            enabled={phase === 'answer' && !alreadyStreamed}
            onComplete={handleAnswerComplete}
          />
        )}

        {/* Phase 3: Sources dropdown (appears after answer completes) */}
        <SourcesDropdown sources={parsed.sources} visible={phase === 'done'} />
      </div>
    </div>
  );
}

/* ─── Rail tab button ──────────────────────────────────────────────────────── */

function RailTabButton({ tab, activeTab, setActiveTab }) {
  const Icon = tab.icon;
  return (
    <button
      type="button"
      onClick={() => setActiveTab(tab.id)}
      className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
        activeTab === tab.id
          ? 'bg-[#F95C4B]/15 text-[#F95C4B] ring-1 ring-[#F95C4B]/25'
          : 'text-[#6b6b6b] hover:bg-[#1a1a1a] hover:text-[#F6F4F1]'
      }`}
    >
      <Icon size={13} />
      {tab.label}
    </button>
  );
}

/* ─── Agent display helper ─────────────────────────────────────────────────── */

function agentDisplayName(name) {
  const normalized = String(name || '').toLowerCase();
  if (normalized.includes('graph')) return 'GraphRAG';
  if (normalized.includes('vangogh') || normalized.includes('content')) return 'Vangogh';
  if (normalized.includes('govern')) return 'Governance';
  if (normalized.includes('strateg')) return 'Strategist';
  return name || 'Agent';
}

/* ─── GPS Pipeline Stage Registry ──────────────────────────────────────────── */

const STAGE_REGISTRY = {
  submit:     { id: 'submit',     label: 'Request Received',    agent: 'Core',        icon: Zap,          color: '#a855f7' },
  routing:    { id: 'routing',    label: 'Route Planning',       agent: 'Strategist',  icon: Navigation,   color: '#3b82f6' },
  evidence:   { id: 'evidence',   label: 'Evidence Gathering',   agent: 'GraphRAG',    icon: Search,       color: '#06b6d4' },
  hitl:       { id: 'hitl',       label: 'Human Checkpoint',     agent: 'User + Core', icon: Users,        color: '#f59e0b' },
  rendering:  { id: 'rendering',  label: 'Artifact Rendering',   agent: 'Vangogh',     icon: Eye,          color: '#ec4899' },
  governance: { id: 'governance', label: 'Governance Review',     agent: 'Governance',  icon: ShieldCheck,  color: '#F95C4B' },
  delivered:  { id: 'delivered',  label: 'Response Delivered',    agent: 'Core',        icon: CheckCircle2, color: '#F95C4B' },
};

/** Build dynamic GPS stages based on which agents the routing decision selected. */
function buildGpsStages(routingDecision, hitlOpen) {
  const stages = [STAGE_REGISTRY.submit, STAGE_REGISTRY.routing];

  if (!routingDecision) {
    // No routing yet — show full default pipeline
    return [
      ...stages,
      STAGE_REGISTRY.evidence,
      STAGE_REGISTRY.hitl,
      STAGE_REGISTRY.rendering,
      STAGE_REGISTRY.governance,
      STAGE_REGISTRY.delivered,
    ];
  }

  const agents = [
    routingDecision.primary_agent,
    ...(routingDecision.helper_agents || []),
    ...(routingDecision.selected_agents || []),
  ]
    .filter(Boolean)
    .map((a) => String(a).toLowerCase());

  const hasGraphRAG = agents.some((a) => a.includes('graph') || a.includes('rag') || a.includes('retriev'));
  const hasContent = agents.some((a) => a.includes('content') || a.includes('vangogh') || a.includes('echo'));
  const hasGovernance = agents.some((a) => a.includes('govern'));

  if (hasGraphRAG) stages.push(STAGE_REGISTRY.evidence);
  if (hitlOpen) stages.push(STAGE_REGISTRY.hitl);
  if (hasContent) stages.push(STAGE_REGISTRY.rendering);
  if (hasGovernance || hasContent) stages.push(STAGE_REGISTRY.governance);

  stages.push(STAGE_REGISTRY.delivered);
  return stages;
}

/* ─── GPS Node ─────────────────────────────────────────────────────────────── */

function GpsNode({ stage, state, isLive, isCurrent, timestamp, eta }) {
  const Icon = stage.icon;
  const isDone = state === 'done';
  const isBlocked = state === 'blocked' || state === 'warning';
  const isIdle = !isDone && !isLive && !isCurrent && !isBlocked;

  return (
    <div className="relative flex items-start gap-4">
      {/* Node circle */}
      <div className="relative z-10 flex flex-col items-center">
        <div
          className={`relative flex h-10 w-10 items-center justify-center rounded-full border-2 transition-all duration-500
            ${isDone
              ? 'border-[#F95C4B] bg-[#F95C4B]/15'
              : isCurrent
                ? 'gps-pulse border-[#F95C4B] bg-[#F95C4B]/20'
                : isBlocked
                  ? 'border-[#ff5c4b] bg-[#ff5c4b]/15'
                  : isIdle
                    ? 'border-[#2a2a2a] bg-[#141414]'
                    : 'border-[#F95C4B]/50 bg-[#F95C4B]/10'
            }`}
        >
          {/* Beacon ring for current */}
          {isCurrent && <div className="gps-beacon absolute inset-0 rounded-full" />}

          <Icon
            size={18}
            className={`transition-all duration-500 ${
              isDone ? 'text-[#F95C4B]'
              : isCurrent ? 'text-[#F95C4B] gps-glow'
              : isBlocked ? 'text-[#ff5c4b]'
              : isIdle ? 'text-[#333]'
              : 'text-[#F95C4B]/70'
            }`}
            strokeWidth={isDone || isCurrent ? 2.5 : 1.5}
          />
        </div>
      </div>

      {/* Content */}
      <div className="min-w-0 flex-1 pt-1">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span
              className={`text-[14px] font-semibold transition-colors duration-300 ${
                isDone ? 'text-[#a1a1a1]'
                : isCurrent ? 'text-white'
                : isBlocked ? 'text-[#ff5c4b]'
                : isIdle ? 'text-[#333]'
                : 'text-[#6b6b6b]'
              }`}
            >
              {stage.label}
            </span>
            {isCurrent && (
              <span className="flex items-center gap-1 rounded-md bg-[#F95C4B]/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-[#F95C4B]">
                <MapPin size={10} className="gps-glow" />
                Here
              </span>
            )}
          </div>
          <span className="text-[11px] font-mono text-[#333]">
            {timestamp || (isIdle ? '' : '--:--')}
          </span>
        </div>

        <div className="mt-0.5 flex items-center gap-2">
          <span
            className="text-[12px]"
            style={{ color: isDone || isCurrent ? stage.color : '#2a2a2a' }}
          >
            {stage.agent}
          </span>
          {isDone && (
            <span className="text-[10px] font-mono text-[#F95C4B]">COMPLETED</span>
          )}
          {isBlocked && (
            <span className="animate-pulse text-[10px] font-mono text-[#ff5c4b]">WAITING</span>
          )}
          {isCurrent && eta && (
            <span className="text-[10px] font-mono text-[#525252]">ETA {eta}</span>
          )}
        </div>
      </div>
    </div>
  );
}

/* ─── GPS Connector Line ───────────────────────────────────────────────────── */

function GpsConnector({ fromDone, toDone, isActive }) {
  return (
    <div className="relative ml-[19px] h-8 w-[2px]">
      {isActive ? (
        /* Animated flowing dashes for active segment */
        <div className="gps-flow-line h-full w-full rounded-full" />
      ) : fromDone && toDone ? (
        /* Solid green for completed segments */
        <div className="h-full w-full rounded-full bg-[#F95C4B]/40" />
      ) : fromDone ? (
        /* Gradient from green to dark for the edge */
        <div className="h-full w-full rounded-full bg-gradient-to-b from-[#F95C4B]/40 to-[#1e1e1e]" />
      ) : (
        /* Dark line for future segments */
        <div className="h-full w-full rounded-full bg-[#1e1e1e]" />
      )}
    </div>
  );
}

/* ─── GPS Plan Tab ─────────────────────────────────────────────────────────── */

function PlanTab({
  workflowPlan,
  activeAgents,
  liveAgents,
  routingDecision,
  renderState,
  hitl,
  workflowComplete,
}) {
  const basePlan = workflowPlan || buildWorkflowPlanFromRouting(routingDecision || {});
  const liveParticipants = useMemo(() => {
    const merged = [...activeAgents, ...liveAgents]
      .filter(Boolean)
      .map((agent) => agentDisplayName(agent));
    merged.push('Core');
    if (hitl.open) merged.push('User');
    return Array.from(new Set(merged));
  }, [activeAgents, hitl.open, liveAgents]);

  const currentStage = basePlan.stages.find((stage) => stage.id === basePlan.currentStageId) || basePlan.stages[0];
  const progressPct = workflowComplete ? 100 : Number(basePlan.progressPct || 0);
  const routeSummary = (routingDecision?.selected_agents || basePlan.selectedAgents || [])
    .map(agentDisplayName)
    .join('  →  ');
  const contentDirectorPlan = basePlan.contentDirectorPlan || {};
  const contentDirectorPages = Array.isArray(contentDirectorPlan.pages) ? contentDirectorPlan.pages : [];

  return (
    <div className="rounded-xl border border-[#e7e5df] bg-white p-4 shadow-[0_8px_28px_rgba(15,23,42,0.06)] md:p-5">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="text-[11px] font-mono uppercase tracking-[0.14em] text-[#7a7a7a]">Core plan</div>
          <div className="mt-1 text-xl font-semibold text-[#111827]">
            {workflowComplete ? 'Workflow complete' : currentStage?.label || 'Awaiting route'}
          </div>
          <div className="mt-1 text-sm leading-relaxed text-[#6b7280]">
            {workflowComplete
              ? 'CORE finished routing, rendering, and governance.'
              : currentStage?.detail || 'CORE is driving the sequence and updating the plan live.'}
          </div>
        </div>
        <div className="relative flex h-16 w-16 items-center justify-center rounded-full border border-[#e7e5df] bg-white shadow-sm">
          <svg className="h-12 w-12 -rotate-90" viewBox="0 0 44 44">
            <circle cx="22" cy="22" r="18" fill="none" stroke="#e7e5df" strokeWidth="3" />
            <circle
              cx="22"
              cy="22"
              r="18"
              fill="none"
              stroke={workflowComplete ? '#111827' : '#0f766e'}
              strokeWidth="3"
              strokeLinecap="round"
              strokeDasharray={`${2 * Math.PI * 18}`}
              strokeDashoffset={`${2 * Math.PI * 18 * (1 - progressPct / 100)}`}
              className="transition-all duration-500"
            />
          </svg>
          <span className="absolute text-[11px] font-semibold text-[#111827]">{progressPct}%</span>
        </div>
      </div>

      {routingDecision && (
        <div className="mb-4 rounded-lg border border-[#e7e5df] bg-[#fafafa] p-4">
          <div className="mb-2 flex items-center gap-2 text-[10px] font-mono uppercase tracking-[0.14em] text-[#0f766e]">
            <GitBranch size={12} /> Route
          </div>
          <div className="text-sm font-medium text-[#111827]">
            {routeSummary || 'Strategist → GraphRAG → Content → Governance'}
          </div>
          {routingDecision.reasoning && (
            <div className="mt-2 text-sm leading-relaxed text-[#6b7280]">{routingDecision.reasoning}</div>
          )}
        </div>
      )}

      {contentDirectorPages.length > 0 && (
        <div className="mb-4 rounded-lg border border-[#e7e5df] bg-[#fafafa] p-4">
          <div className="mb-2 flex items-center gap-2 text-[10px] font-mono uppercase tracking-[0.14em] text-[#111827]">
            <FileCog size={12} /> Content Director
          </div>
          <div className="text-sm font-medium text-[#111827]">
            {contentDirectorPlan.overall_strategy || 'Page-by-page plan ready'}
          </div>
          <div className="mt-1 text-xs text-[#6b7280]">{contentDirectorPages.length} pages planned</div>
        </div>
      )}

      {hitl.open && (
        <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-amber-900">
          <div className="text-[10px] font-mono uppercase tracking-[0.14em]">HITL</div>
          <div className="mt-1 text-sm font-medium">
            {hitl.agentNode === 'content_page_review' ? 'Page review required' : 'Clarification required'}
          </div>
          <div className="mt-1 text-xs leading-relaxed">
            {hitl.questions.length} question{hitl.questions.length === 1 ? '' : 's'} pending before the workflow resumes.
          </div>
        </div>
      )}

      <div className="space-y-3">
        {basePlan.stages.map((stage) => {
          const isCurrent = stage.id === basePlan.currentStageId;
          const statusClass =
            stage.state === 'done'
              ? 'border-[#d8e8e0] bg-[#f6fbf8] text-[#0f766e]'
              : stage.state === 'blocked'
                ? 'border-amber-200 bg-amber-50 text-amber-800'
                : stage.state === 'active'
                  ? 'border-[#d7e5df] bg-[#f0fbf7] text-[#0f766e]'
                  : 'border-[#e7e5df] bg-white text-[#6b7280]';

          return (
            <div key={stage.id} className={`rounded-lg border p-4 transition-all ${isCurrent ? 'shadow-[0_10px_24px_rgba(15,23,42,0.05)]' : ''} ${statusClass}`}>
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold">{stage.label}</div>
                  <div className="mt-1 text-xs opacity-80">{stage.agent}</div>
                </div>
                <div className="rounded-full border border-current/20 px-2.5 py-1 text-[10px] font-mono uppercase tracking-[0.14em]">
                  {stage.state}
                </div>
              </div>
              {stage.detail && <div className="mt-2 text-xs leading-relaxed opacity-80">{stage.detail}</div>}
            </div>
          );
        })}
      </div>

      <div className="mt-4 rounded-lg border border-[#e7e5df] bg-[#fafafa] p-4">
        <div className="mb-2 text-[10px] font-mono uppercase tracking-[0.14em] text-[#7a7a7a]">Live participants</div>
        <div className="flex flex-wrap gap-2">
          {liveParticipants.map((label) => (
            <span key={label} className="rounded-full border border-[#e7e5df] bg-white px-3 py-1 text-xs text-[#374151]">
              {label}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ─── Main Chat Page ───────────────────────────────────────────────────────── */

export default function ChatPage() {
  const {
    messages,
    query,
    setQuery,
    activeTab,
    setActiveTab,
    workflowMode,
    setWorkflowMode,
    previewHtml,
    schema,
    governance,
    workflowPlan,
    workflowComplete,
    timeline,
    hitl,
    setHitl,
    renderState,
    isSubmitting,
    isResuming,
    rightRailOpen,
    submit,
    resume,
    promptSuggestions,
    activeAgents,
    liveAgents,
    routingDecision,
    lastEventType,
    isThinking,
    thinkingLabel,
    isDayMode,
  } = useBlaiqWorkspace();

  const d = isDayMode;

  const transcriptRef = useRef(null);
  const atBottomRef = useRef(true);
  const [hitlStep, setHitlStep] = useState(0);

  const currentHitlQuestion = useMemo(
    () => hitl.questions[hitlStep] || '',
    [hitl.questions, hitlStep]
  );
  const currentHitlKey = `q${hitlStep + 1}`;
  const isLastHitlStep = hitlStep >= Math.max(0, hitl.questions.length - 1);

  function updateHitlAnswer(value) {
    setHitl((current) => ({
      ...current,
      answers: { ...current.answers, [currentHitlKey]: value },
    }));
  }

  function moveHitlStep(direction) {
    setHitlStep((current) => {
      const next = current + direction;
      if (next < 0) return 0;
      if (next > Math.max(0, hitl.questions.length - 1)) return Math.max(0, hitl.questions.length - 1);
      return next;
    });
  }

  function handleHitlChip(chip) {
    updateHitlAnswer(chip);
    if (!isLastHitlStep) moveHitlStep(1);
  }

  useEffect(() => {
    const el = transcriptRef.current;
    if (!el) return;
    const onScroll = () => {
      atBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    };
    onScroll();
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, []);

  // Only auto-scroll when a NEW message is added (not during streaming/re-renders)
  const prevMsgCountRef = useRef(0);
  useEffect(() => {
    const el = transcriptRef.current;
    if (!el) return;
    // Scroll only when message count increases (new message arrived)
    if (messages.length > prevMsgCountRef.current) {
      // Scroll the new message into view but don't force to bottom
      el.scrollTop = el.scrollHeight;
    }
    prevMsgCountRef.current = messages.length;
  }, [messages.length]);

  useEffect(() => {
    if (!hitl.open) { setHitlStep(0); return; }
    setHitlStep((current) => Math.min(current, Math.max(0, hitl.questions.length - 1)));
  }, [hitl.open, hitl.questions.length]);

  const hasMessages = messages.length > 0;
  const showHero = !hasMessages && !rightRailOpen;

  /* ── Single layout: gradient bg, input always at bottom, hero fades out ── */
  return (
    <div className={`h-full grid min-h-0 overflow-hidden ${
      rightRailOpen
        ? 'grid-cols-[minmax(0,1fr)_minmax(320px,30vw)] max-xl:grid-cols-[minmax(0,1fr)]'
        : 'grid-cols-[minmax(0,1fr)]'
    }`}>
      {/* ── Main column (always present — hero content + messages + input) ── */}
      <section className="grid min-h-0 grid-rows-[minmax(0,1fr)_auto] overflow-hidden">
        {/* Scrollable content area */}
        <div ref={transcriptRef} className="light-scrollbar relative min-h-0 overflow-y-auto">
          {/* Hero content — fades out when messages appear */}
          <div
            className="absolute inset-0 flex flex-col items-center justify-center px-6"
            style={{
              opacity: showHero ? 1 : 0,
              transform: showHero ? 'translateY(0)' : 'translateY(60px)',
              pointerEvents: showHero ? 'auto' : 'none',
              transition: 'opacity 0.8s ease-out, transform 0.8s ease-out',
            }}
          >
            {/* Announcement banner */}
            <div className={`mb-8 flex items-center gap-2 rounded-full border border-[#F95C4B]/25 px-4 py-1.5 backdrop-blur-md ${d ? 'bg-[#F95C4B]/[0.06]' : 'bg-[#F95C4B]/[0.08]'}`}>
              <span className="rounded-full bg-[#F95C4B] px-2 py-0.5 text-[10px] font-bold uppercase text-white">New</span>
              <span className={`text-[13px] ${d ? 'text-[#333]' : 'text-[#F6F4F1]/80'}`}>Introducing a smarter BLAIQ</span>
            </div>
            <h1 className={`text-center text-[42px] font-semibold leading-tight tracking-tight md:text-[52px] ${d ? 'text-[#000]' : 'text-[#F6F4F1]'}`}>
              What can I help with?
            </h1>
            <p className={`mt-3 text-center text-[16px] ${d ? 'text-[#525252]/70' : 'text-[#E4DED2]/50'}`}>
              Powered by GraphRAG · Temporal · Multi-agent orchestration
            </p>
          </div>

          {/* Messages — fades in when messages appear */}
          <div
            className="px-4 pb-6 pt-4 md:px-8"
            style={{
              opacity: showHero ? 0 : 1,
              transform: showHero ? 'translateY(30px)' : 'translateY(0)',
              transition: 'opacity 0.6s ease-out 0.3s, transform 0.6s ease-out 0.3s',
            }}
          >
            <div className="mx-auto flex w-full max-w-[860px] flex-col gap-4">
              {messages.map((item) => (
                <MessageCard key={item.id} item={item} />
              ))}

              {/* Thinking bubble */}
              {isThinking && (
                <div className="flex justify-start animate-[fadeIn_0.4s_ease-out]">
                  <div className={`rounded-2xl px-5 py-4 backdrop-blur-xl ${d ? 'border border-[#E4DED2] bg-white/80 shadow-sm' : 'border border-white/[0.06] bg-black/30'}`}>
                    <div className="flex items-center gap-3">
                      <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[#F95C4B]/15">
                        <Bot size={14} className="text-[#F95C4B]" />
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-[13px] font-semibold text-white">Thinking</span>
                          <span className="relative flex h-2 w-2">
                            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#F95C4B] opacity-75" />
                            <span className="relative inline-flex h-2 w-2 rounded-full bg-[#F95C4B]" />
                          </span>
                        </div>
                        <div className={`mt-0.5 text-[12px] ${d ? 'text-[#9a9a9a]' : 'text-[#525252]'}`}>{thinkingLabel || 'Processing'}</div>
                      </div>
                    </div>
                    <div className="mt-3 flex gap-1.5">
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[#F95C4B]/60" style={{ animationDelay: '0ms' }} />
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[#F95C4B]/60" style={{ animationDelay: '150ms' }} />
                      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-[#F95C4B]/60" style={{ animationDelay: '300ms' }} />
                    </div>
                    {renderState.loading && renderState.total > 0 && (
                      <div className="mt-3 flex items-center gap-3">
                        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[#1a1a1a]">
                          <div className="h-full rounded-full bg-[#F95C4B] transition-all"
                            style={{ width: `${Math.min(100, Math.max(8, (renderState.section / Math.max(1, renderState.total)) * 100))}%` }}
                          />
                        </div>
                        <div className="text-xs font-mono text-[#525252]">{renderState.section}/{renderState.total}</div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Input bar — always at bottom, same element in both states */}
        <div className={`border-t px-4 pb-5 pt-3 backdrop-blur-xl md:px-8 ${d ? 'border-[#E4DED2] bg-[#F6F4F1]/80' : 'border-[#F95C4B]/20 bg-[#0d0606]/95'}`}>
          <div className="mx-auto w-full max-w-[820px]">
            <div className="relative">
              {/* HITL overlay */}
              {hitl.open && (
                <div className="absolute bottom-[calc(100%+10px)] left-1/2 z-20 w-full max-w-[560px] -translate-x-1/2 overflow-hidden rounded-2xl border border-[#2a2a2a] bg-[#141414]/95 shadow-2xl backdrop-blur-xl">
                  <div className="flex items-center justify-between border-b border-[#1e1e1e] px-4 py-2.5">
                    <div className="text-[11px] font-mono uppercase tracking-wider text-[#525252]">Clarification needed</div>
                    <div className="flex items-center gap-3">
                      <div className="text-[11px] font-mono text-[#525252]">{hitlStep + 1} / {Math.max(hitl.questions.length, 1)}</div>
                      <div className="text-[11px] font-mono text-[#F95C4B]">{hitl.agentNode}</div>
                    </div>
                  </div>
                  <div className="px-4 py-4">
                    <div className="rounded-xl bg-[#1a1a1a] px-4 py-4">
                      <div className="mb-1 text-[10px] font-mono uppercase tracking-wider text-[#525252]">{hitlStep + 1}. Question</div>
                      <div className="mb-3 text-sm font-medium leading-6 text-white">{currentHitlQuestion}</div>
                      <input
                        value={hitl.answers[currentHitlKey] || ''}
                        onChange={(e) => updateHitlAnswer(e.target.value)}
                        onKeyDown={(e) => { if (e.key !== 'Enter') return; e.preventDefault(); if (isLastHitlStep) { resume(); return; } moveHitlStep(1); }}
                        className="mb-3 w-full rounded-lg border border-[#2a2a2a] bg-[#0f0f0f] px-3 py-2.5 text-sm text-[#F6F4F1] outline-none placeholder:text-[#525252] focus:border-[#F95C4B]/40"
                      />
                      <div className="flex flex-wrap gap-2">
                        {quickChips(currentHitlQuestion).map((chip) => (
                          <button key={chip} type="button" onClick={() => handleHitlChip(chip)}
                            className="rounded-full border border-[#2a2a2a] bg-[#0f0f0f] px-2.5 py-1 text-[11px] text-[#a1a1a1] hover:border-[#F95C4B]/30 hover:text-[#F95C4B]">{chip}</button>
                        ))}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center justify-between px-4 pb-4">
                    <button type="button" onClick={() => moveHitlStep(-1)} disabled={hitlStep === 0}
                      className="flex h-8 w-8 items-center justify-center rounded-full border border-[#2a2a2a] text-[#a1a1a1] hover:text-[#F95C4B] disabled:opacity-30"><ChevronLeft size={14} /></button>
                    <button type="button" disabled={isResuming}
                      onClick={() => { if (isLastHitlStep) { resume(); return; } moveHitlStep(1); }}
                      className="inline-flex items-center gap-2 rounded-full bg-white px-4 py-2 text-xs font-semibold text-[#0a0a0a] hover:bg-[#e5e5e5] disabled:opacity-50">
                      {isResuming ? 'Resuming...' : isLastHitlStep ? 'Continue rendering' : 'Next'}
                      {!isResuming && <ChevronRight size={14} />}
                    </button>
                  </div>
                </div>
              )}

              {/* Input bar — Claude-style */}
              <div className={`rounded-2xl ring-1 ring-[#F95C4B]/20 backdrop-blur-xl ${d ? 'bg-white shadow-[0_4px_24px_rgba(0,0,0,0.08)]' : 'bg-[#1a0e0e] shadow-[0_8px_40px_rgba(0,0,0,0.6)]'}`}>
                {/* Textarea */}
                <textarea
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    const t = e.target;
                    t.style.height = 'auto';
                    t.style.height = Math.min(t.scrollHeight, 160) + 'px';
                  }}
                  onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); } }}
                  rows={1}
                  placeholder={showHero ? 'Ask BLAIQ anything...' : 'Follow up...'}
                  className={`w-full resize-none bg-transparent px-4 pt-4 pb-2 text-[15px] leading-relaxed outline-none ${d ? 'text-[#000] placeholder:text-[#aaa]' : 'text-[#F6F4F1] placeholder:text-[#3a3a3a]'}`}
                  style={{ maxHeight: '160px' }}
                />
                {/* Toolbar */}
                <div className="flex items-center justify-between px-3 pb-3 pt-1">
                  {/* Left: attach / mode / think */}
                  <div className="flex items-center gap-0.5">
                    <button
                      type="button"
                      title="Attach file"
                      className={`flex h-8 w-8 items-center justify-center rounded-lg transition-colors ${d ? 'text-[#9a9a9a] hover:bg-[#E4DED2] hover:text-[#333]' : 'text-[#525252] hover:bg-[#1e1e1e] hover:text-[#a1a1a1]'}`}
                    >
                      <Paperclip size={15} />
                    </button>
                    <button
                      type="button"
                      onClick={() => { const m = ['standard','deep_research','creative']; setWorkflowMode(m[(m.indexOf(workflowMode)+1)%m.length]); }}
                      className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12px] font-medium transition-colors ${d ? 'text-[#9a9a9a] hover:bg-[#E4DED2] hover:text-[#333]' : 'text-[#525252] hover:bg-[#1e1e1e] hover:text-[#a1a1a1]'}`}
                    >
                      <Sparkles size={13} />
                      {workflowMode === 'standard' ? 'Plan' : workflowMode === 'deep_research' ? 'Deep' : 'Creative'}
                    </button>
                    <button
                      type="button"
                      title="Extended thinking"
                      className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12px] font-medium transition-colors ${d ? 'text-[#9a9a9a] hover:bg-[#E4DED2] hover:text-[#333]' : 'text-[#525252] hover:bg-[#1e1e1e] hover:text-[#a1a1a1]'}`}
                    >
                      <BrainCircuit size={13} />
                      Think
                    </button>
                  </div>
                  {/* Right: mic / send */}
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      title="Voice input"
                      className={`flex h-8 w-8 items-center justify-center rounded-lg transition-colors ${d ? 'text-[#9a9a9a] hover:bg-[#E4DED2] hover:text-[#333]' : 'text-[#525252] hover:bg-[#1e1e1e] hover:text-[#a1a1a1]'}`}
                    >
                      <Mic size={15} />
                    </button>
                    <button
                      type="button"
                      onClick={submit}
                      disabled={!query.trim() || isSubmitting || isResuming}
                      className="flex h-8 w-8 items-center justify-center rounded-full bg-[#F95C4B] text-white shadow-[0_2px_12px_rgba(249,92,75,0.35)] transition-all hover:bg-[#e04d3d] hover:shadow-[0_4px_16px_rgba(249,92,75,0.5)] disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {isSubmitting ? <Loader2 size={14} className="animate-spin" /> : <ArrowUp size={14} strokeWidth={2.5} />}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Right rail — slides in from right ────────────────────────────────── */}
      {rightRailOpen && (
        <aside className={`min-h-0 overflow-hidden border-l px-4 pb-4 pt-3 backdrop-blur-xl max-xl:border-l-0 max-xl:border-t animate-[slideInRight_1s_cubic-bezier(0.16,1,0.3,1)_both] ${d ? 'border-[#E4DED2] bg-[#F6F4F1]/80' : 'border-[#1e1e1e] bg-[#0a0a0a]/80'}`}
        >
          <div className="mb-3 flex flex-wrap gap-1">
            {tabs.map((tab) => (
              <RailTabButton key={tab.id} tab={tab} activeTab={activeTab} setActiveTab={setActiveTab} />
            ))}
          </div>
          <div className="light-scrollbar h-[calc(100%-44px)] overflow-y-auto">
            {activeTab === 'preview' ? (
              <div className="h-full rounded-xl border border-[#e3e0db] bg-[#faf9f4] p-3">
                <div className="mb-3 flex items-center justify-between px-1">
                  <div>
                    <div className="text-[10px] font-mono uppercase tracking-wider text-[#7a7267]">Preview</div>
                    <div className="text-sm font-semibold text-[#111111]">
                      {previewHtml ? 'Live artifact' : renderState.loading ? 'Rendering pages' : 'Waiting for output'}
                    </div>
                  </div>
                  <div className="rounded-md border border-[#e3e0db] bg-white px-2.5 py-1 text-[11px] text-[#6b6b6b]">{renderState.artifactKind || 'content'}</div>
                </div>
                <div className="h-[calc(100%-52px)] overflow-hidden rounded-lg border border-[#e3e0db] bg-white">
                  {previewHtml ? (
                    <iframe title="Artifact preview" srcDoc={normalizePreviewHtml(previewHtml)} className="h-full w-full" />
                  ) : (
                    <div className="flex h-full flex-col items-center justify-center gap-4 bg-[#faf9f4] px-6 text-center">
                      <PanelRight size={24} className="text-[#ff5c4b]" />
                      <div className="max-w-xs text-sm font-semibold text-[#111111]">
                        {renderState.loading ? 'Rendering is in progress' : 'Preview is waiting for the first artifact fragment'}
                      </div>
                      {renderState.loading ? (
                        <div className="w-full max-w-[220px] rounded-full bg-[#e3e0db]">
                          <div
                            className="h-2 rounded-full bg-[#ff5c4b]"
                            style={{ width: `${Math.min(100, Math.max(8, renderState.total ? (renderState.section / Math.max(1, renderState.total)) * 100 : 12))}%` }}
                          />
                        </div>
                      ) : null}
                    </div>
                  )}
                </div>
              </div>
            ) : null}

            {activeTab === 'plan' ? (
              <PlanTab
                activeAgents={activeAgents}
                liveAgents={liveAgents}
                routingDecision={routingDecision}
                renderState={renderState}
                hitl={hitl}
                workflowPlan={workflowPlan}
                workflowComplete={workflowComplete || lastEventType === 'complete' || lastEventType === 'regen_complete'}
              />
            ) : null}

            {activeTab === 'schema' ? (
              <div className="rounded-xl border border-[#1e1e1e] bg-[#0f0f0f] p-4">
                <div className="mb-4 text-sm font-semibold text-white">Schema</div>
                {schema ? (
                  <pre className="overflow-auto rounded-lg bg-[#141414] p-3 text-xs leading-relaxed text-[#a1a1a1]">{JSON.stringify(schema, null, 2)}</pre>
                ) : (
                  <div className="text-sm text-[#525252]">Schema appears here when Vangogh returns structured content.</div>
                )}
              </div>
            ) : null}

            {activeTab === 'governance' ? (
              <div className="rounded-xl border border-[#1e1e1e] bg-[#0f0f0f] p-4">
                <div className="mb-4 text-sm font-semibold text-white">Governance</div>
                {governance ? (
                  <div className="space-y-2">
                    <div
                      className={`rounded-lg px-3 py-2 text-sm font-medium ${
                        governance.validation_passed
                          ? 'bg-[#F95C4B]/10 text-[#F95C4B]'
                          : 'bg-[#ff5c4b]/10 text-[#ff5c4b]'
                      }`}
                    >
                      {governance.validation_passed ? 'Validation passed' : 'Review required'}
                    </div>
                    {(governance.policy_checks || []).map((check) => (
                      <div key={`${check.rule}-${check.detail}`} className="rounded-lg bg-[#141414] p-3">
                        <div className="text-sm font-medium text-white">{check.rule}</div>
                        <div className="mt-1 text-xs text-[#525252]">{check.detail}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-sm text-[#525252]">Governance results will appear here after the artifact is evaluated.</div>
                )}
              </div>
            ) : null}
          </div>
        </aside>
      )}
    </div>
  );
}

export function ChatPanel() {
  return null;
}
