import React, { useEffect, useState, useCallback, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Sparkles, Save, RotateCcw, Eye, Upload, FileText, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';
import { useBlaiqWorkspace } from '../shared/blaiq-workspace-context';
import '../shared/bmw-reference-theme.css';

const DEFAULT_DNA = {
  theme: 'Custom Brand',
  version: '1.0',
  description: '',
  tokens: {
    primary: '#FFFFFF',
    background: '#0F1115',
    surface: '#151922',
    border: '#262C37',
    accent_blue: '#1C69D4',
    accent_emerald: '#2E8B57',
    accent_purple: '#0653B6',
    muted: '#757575',
    ink: '#262626',
  },
  typography: {
    headings: 'BMWTypeNextLatin Light, Helvetica, Arial, sans-serif',
    body: 'BMWTypeNextLatin, Helvetica, Arial, sans-serif',
    title_massive: 'text-6xl font-bold tracking-tight',
    body_default: 'text-base leading-relaxed',
  },
  effects: [],
  component_mappings: {},
  layout_patterns: {},
  glassmorphism: {},
};

const clone = (value) => JSON.parse(JSON.stringify(value));

const DEFAULT_BRAND_DOC = {
  schema_version: 'brand-dna/v2',
  meta: { tenant_id: 'default', extraction_mode: 'manual' },
  sources: [],
  evidence: { raw_brand_dna: null, warnings: [] },
  design_readme: '',
  layers: {
    extracted: null,
    normalized: {},
    designer_handoff: {},
    compiled: clone(DEFAULT_DNA),
  },
  compiled: clone(DEFAULT_DNA),
  ...clone(DEFAULT_DNA),
};

const ACCEPTED_UPLOADS = 'image/*,application/pdf,.doc,.docx,text/plain';
const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;

function isSupportedUpload(file) {
  const type = (file.type || '').toLowerCase();
  const name = (file.name || '').toLowerCase();
  if (type.startsWith('image/')) return true;
  if (type === 'application/pdf' || type === 'text/plain') return true;
  if (name.endsWith('.doc') || name.endsWith('.docx')) return true;
  return false;
}

function coerceBrandDocument(payload) {
  if (!payload) return clone(DEFAULT_BRAND_DOC);

  if (payload.schema_version === 'brand-dna/v2') {
    const compiled = { ...clone(DEFAULT_DNA), ...(payload.compiled || {}) };
    compiled.tokens = { ...clone(DEFAULT_DNA.tokens), ...(payload.compiled?.tokens || payload.tokens || {}) };
    compiled.typography = { ...clone(DEFAULT_DNA.typography), ...(payload.compiled?.typography || payload.typography || {}) };
    compiled.effects = Array.isArray(payload.compiled?.effects) ? payload.compiled.effects : (Array.isArray(payload.effects) ? payload.effects : []);
    return {
      ...clone(DEFAULT_BRAND_DOC),
      ...payload,
      compiled,
      layers: {
        ...clone(DEFAULT_BRAND_DOC.layers),
        ...(payload.layers || {}),
        compiled,
      },
      theme: compiled.theme,
      version: compiled.version,
      description: compiled.description,
      tokens: compiled.tokens,
      typography: compiled.typography,
      effects: compiled.effects,
    };
  }

  const compiled = {
    ...clone(DEFAULT_DNA),
    ...payload,
    tokens: { ...clone(DEFAULT_DNA.tokens), ...(payload.tokens || {}) },
    typography: { ...clone(DEFAULT_DNA.typography), ...(payload.typography || {}) },
    effects: Array.isArray(payload.effects) ? payload.effects : [],
  };

  return {
    ...clone(DEFAULT_BRAND_DOC),
    compiled,
    layers: { ...clone(DEFAULT_BRAND_DOC.layers), compiled },
    theme: compiled.theme,
    version: compiled.version,
    description: compiled.description,
    tokens: compiled.tokens,
    typography: compiled.typography,
    effects: compiled.effects,
  };
}

function buildSaveDocument(brandDoc, compiled) {
  const doc = coerceBrandDocument(brandDoc);
  const nextCompiled = {
    ...doc.compiled,
    ...compiled,
    tokens: { ...doc.compiled.tokens, ...(compiled.tokens || {}) },
    typography: { ...doc.compiled.typography, ...(compiled.typography || {}) },
    effects: Array.isArray(compiled.effects) ? compiled.effects : doc.compiled.effects,
  };
  return {
    ...doc,
    compiled: nextCompiled,
    layers: { ...doc.layers, compiled: nextCompiled },
    theme: nextCompiled.theme,
    version: nextCompiled.version,
    description: nextCompiled.description,
    tokens: nextCompiled.tokens,
    typography: nextCompiled.typography,
    effects: nextCompiled.effects,
  };
}

export default function BrandDna() {
  const { apiBase, sessionId } = useBlaiqWorkspace();
  const [brandDoc, setBrandDoc] = useState(null);
  const [dna, setDna] = useState(null);
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [uploads, setUploads] = useState([]);
  const [extracting, setExtracting] = useState(false);
  const [extractionJob, setExtractionJob] = useState(null);
  const fileInputRef = useRef(null);
  const pollTimeoutRef = useRef(null);
  const extractionBadgeTimeoutRef = useRef(null);

  const [recentlyExtracted, setRecentlyExtracted] = useState(false);
  const [previewMode, setPreviewMode] = useState('detailed');
  const [uploadError, setUploadError] = useState('');
  const [dragActive, setDragActive] = useState(false);
  const [extractionLogs, setExtractionLogs] = useState([]);

  const tenantId = 'default';
  const base = apiBase || '';

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${base}/api/v1/brand-dna/${tenantId}`);
      const data = await res.json();
      const doc = coerceBrandDocument(data.brand_dna);
      setBrandDoc(doc);
      setDna(doc.compiled || clone(DEFAULT_DNA));
      setLoaded(true);
    } catch {
      const fallback = clone(DEFAULT_BRAND_DOC);
      setBrandDoc(fallback);
      setDna(fallback.compiled || clone(DEFAULT_DNA));
      setLoaded(true);
    }
  }, [base, tenantId]);

  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true);
    try {
      const payload = buildSaveDocument(brandDoc, dna);
      await fetch(`${base}/api/v1/brand-dna/${tenantId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      setBrandDoc(payload);
    } finally {
      setSaving(false);
    }
  };

  const uploadFiles = useCallback(async (files) => {
    if (!files.length) return;
    setUploadError('');

    const validFiles = [];
    const rejectedNames = [];

    files.forEach((file) => {
      if (!isSupportedUpload(file) || file.size > MAX_UPLOAD_BYTES) {
        rejectedNames.push(file.name);
        return;
      }
      validFiles.push(file);
    });

    if (rejectedNames.length > 0) {
      setUploadError(`Skipped unsupported files: ${rejectedNames.join(', ')}`);
    }
    if (!validFiles.length) return;

    for (const file of validFiles) {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('tenant_id', tenantId);
      if (sessionId) formData.append('thread_id', sessionId);

      const tempId = Math.random().toString(36).slice(2);
      setUploads(prev => [...prev, { id: tempId, name: file.name, status: 'uploading' }]);

      try {
        const res = await fetch(`${base}/api/v1/upload`, {
          method: 'POST',
          body: formData,
        });
        const data = await res.json();
        setUploads(prev => prev.map(u => u.id === tempId ? { ...u, uploadId: data.upload_id, status: 'ready' } : u));
      } catch {
        setUploads(prev => prev.map(u => u.id === tempId ? { ...u, status: 'failed' } : u));
      }
    }
  }, [base, sessionId, tenantId]);

  const handleFileUpload = async (e) => {
    const files = Array.from(e.target.files || []);
    await uploadFiles(files);
    e.target.value = '';
  };

  const handleDrop = async (event) => {
    event.preventDefault();
    setDragActive(false);
    const files = Array.from(event.dataTransfer?.files || []);
    await uploadFiles(files);
  };

  const readyUploadCount = uploads.filter((u) => u.status === 'ready').length;
  const appendExtractionLog = useCallback((line) => {
    setExtractionLogs((prev) => (prev.includes(line) ? prev : [...prev, line]));
  }, []);

  const startAnalysis = async () => {
    const uploadIds = uploads.filter(u => u.status === 'ready').map(u => u.uploadId);
    if (!uploadIds.length) return;

    setExtracting(true);
    setExtractionLogs([
      'Queued extraction job',
      'Preparing visual assets for Qwen analysis',
    ]);
    try {
      const res = await fetch(`${base}/api/v1/brand-dna/${tenantId}/extract`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ upload_ids: uploadIds, mode: 'auto' }),
      });
      const data = await res.json();
      appendExtractionLog(`Job accepted: ${data.job_id}`);
      pollJob(data.job_id);
    } catch {
      setExtracting(false);
      appendExtractionLog('Failed to submit extraction job');
    }
  };

  const pollJob = async (jobId) => {
    if (pollTimeoutRef.current) {
      window.clearTimeout(pollTimeoutRef.current);
      pollTimeoutRef.current = null;
    }

    let attempt = 0;
    const check = async () => {
      try {
        const res = await fetch(`${base}/api/v1/brand-dna/${tenantId}/extract/${jobId}`);
        const data = await res.json();
        setExtractionJob(data);
        if (typeof data.progress === 'number') {
          if (data.progress >= 10) appendExtractionLog('Extraction started');
          if (data.progress >= 20) appendExtractionLog('Assets validated and sampled');
          if (data.progress >= 55) appendExtractionLog('Visual DNA parsed from model output');
          if (data.progress >= 80) appendExtractionLog('Compiling detailed DESIGN.md and runtime tokens');
        }
        if (data.intermediate) {
          appendExtractionLog('Intermediate visual analysis available');
        }

        if (data.brand_dna) {
          const doc = coerceBrandDocument(data.brand_dna);
          setBrandDoc(doc);
          setDna(doc.compiled || clone(DEFAULT_DNA));
          setPreviewMode((prev) => prev || 'live');
          setRecentlyExtracted(true);
          if (extractionBadgeTimeoutRef.current) {
            window.clearTimeout(extractionBadgeTimeoutRef.current);
          }
          extractionBadgeTimeoutRef.current = window.setTimeout(() => {
            setRecentlyExtracted(false);
            extractionBadgeTimeoutRef.current = null;
          }, 4000);
        }

        if (data.status === 'succeeded') {
          setExtracting(false);
          appendExtractionLog('Extraction completed successfully');
        } else if (data.status === 'failed') {
          setExtracting(false);
          appendExtractionLog(`Extraction failed: ${data.error_message || 'Unknown error'}`);
        } else {
          attempt += 1;
          appendExtractionLog(`Buffering model response... poll #${attempt}`);
          const nextDelay = attempt < 3 ? 1500 : attempt < 8 ? 3000 : 5000;
          pollTimeoutRef.current = window.setTimeout(check, nextDelay);
        }
      } catch {
        setExtracting(false);
        appendExtractionLog('Polling interrupted due to network/runtime error');
      }
    };
    check();
  };

  useEffect(() => () => {
    if (pollTimeoutRef.current) {
      window.clearTimeout(pollTimeoutRef.current);
      pollTimeoutRef.current = null;
    }
    if (extractionBadgeTimeoutRef.current) {
      window.clearTimeout(extractionBadgeTimeoutRef.current);
      extractionBadgeTimeoutRef.current = null;
    }
  }, []);

  if (!loaded || !dna) {
    return <div className="flex h-full items-center justify-center text-sm text-[#6b7280]">Loading brand DNA...</div>;
  }

  const tokens = dna.tokens || {};
  const typo = dna.typography || {};
  const designReadme = brandDoc?.design_readme || '';
  const previewReady = Boolean(extractionJob?.brand_dna || brandDoc?.meta?.extraction_mode === 'visual-preview' || brandDoc?.meta?.extraction_mode === 'auto');
  const isPreviewDraft = extractionJob?.status !== 'succeeded' && brandDoc?.meta?.extraction_mode === 'visual-preview';
  const normalizedComposition = brandDoc?.layers?.normalized?.visual_system?.composition || {};
  const extractedComposition = brandDoc?.layers?.extracted?.visual_system?.composition || {};
  const compositionHint = [
    normalizedComposition.grid_style,
    normalizedComposition.density,
    normalizedComposition.focal_element_strategy,
    extractedComposition.layout_archetype,
    extractedComposition.grid_style,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
  const isDashboardStyle = /(dashboard|data|metric|kpi|grid|card|tile|module)/.test(compositionHint);
  const extractionStage = !extracting
    ? 'Idle'
    : extractionJob?.progress >= 80
      ? 'Generating detailed design system guide'
      : extractionJob?.progress >= 55
        ? 'Normalizing visual language and token mapping'
        : extractionJob?.progress >= 20
          ? 'Buffering visual inputs and analyzing composition'
          : 'Extracting brand DNA';
  const predefinedUxSuggestions = [
    'Define interaction hierarchy: one primary CTA per major viewport section.',
    'Enforce a fixed spacing rhythm with constrained density bands.',
    'Use semantic color roles for status and avoid decorative color noise.',
    'Pair headline scale with compact body copy to improve scannability.',
    'Introduce consistent card anatomy: title, value, context, action.',
  ];

  return (
    <div className="bmw-page h-full min-h-0 overflow-hidden">
      <div className="mx-auto flex h-full w-full max-w-[1400px] flex-col gap-4 overflow-y-auto p-5 pb-8 md:p-7">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="text-[12px] font-mono uppercase tracking-[0.18em] text-[#7a7267]">Visual Intelligence Workspace</div>
          <div className="flex items-center gap-2">
            <button
              onClick={load}
              className="bmw-button-secondary ml-auto flex items-center gap-1.5 px-3 py-1.5 text-[12px]"
            >
              <RotateCcw size={13} /> Reset
            </button>
            <button
              onClick={save}
              disabled={saving}
              className="bmw-button-primary flex items-center gap-1.5 px-4 py-1.5 text-[12px] disabled:opacity-50"
            >
              <Save size={13} /> {saving ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>

        <section className="rounded-[24px] border border-[rgba(0,0,0,0.08)] bg-[#faf9f4] p-4 shadow-sm md:p-5">
          <div className="mb-3 text-[15px] font-semibold tracking-[0.02em] text-[#262626]">Upload</div>
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
            <div
              className={`rounded-[18px] border border-dashed p-6 transition ${
                dragActive
                  ? 'border-[#1c69d4] bg-[#eef5ff]'
                  : 'border-[#e3e0db] bg-white/70 hover:bg-white'
              }`}
              onDrop={handleDrop}
              onDragOver={(event) => {
                event.preventDefault();
                setDragActive(true);
              }}
              onDragLeave={(event) => {
                event.preventDefault();
                setDragActive(false);
              }}
            >
              <div className="flex flex-col items-center gap-3 text-center">
                <div className="h-11 w-11 rounded-full bg-[#f3f4f6] text-[#6b7280] grid place-items-center">
                  <Upload size={20} />
                </div>
                <div>
                  <div className="text-[15px] font-semibold tracking-[0.02em] text-[#262626]">Upload Brand Assets</div>
                  <div className="mt-1 text-[12px] leading-5 text-[#6b7280]">
                    Drop files here or choose files to extract visual language, color, type, and style system.
                  </div>
                </div>
                <input type="file" multiple ref={fileInputRef} onChange={handleFileUpload} className="hidden" accept={ACCEPTED_UPLOADS} />
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="rounded-full border border-[#e3e0db] bg-white px-5 py-2 text-[13px] font-medium text-[#111827] hover:bg-[#f9f9f9]"
                >
                  Choose Files
                </button>
                <div className="text-[11px] text-[#7a7267]">PNG, JPG, WEBP, PDF, DOC, DOCX, TXT · max 20MB each</div>
              </div>
            </div>

            <div className="rounded-[18px] border border-[rgba(0,0,0,0.06)] bg-white p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <div className="text-[14px] font-semibold tracking-[0.02em]">Uploaded Assets ({uploads.length})</div>
                  <div className="text-[11px] text-[#6b7280]">{readyUploadCount} ready for extraction</div>
                </div>
                <button
                  onClick={startAnalysis}
                  disabled={extracting || readyUploadCount === 0}
                  className="bmw-button-primary flex items-center gap-2 px-4 py-1.5 text-[12px] disabled:opacity-50"
                >
                  {extracting ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
                  {extracting ? `Analyzing (${extractionJob?.progress || 0}%)` : 'Analyze'}
                </button>
              </div>
              {uploads.length === 0 ? (
                <div className="rounded-[12px] border border-[#e3edee] bg-[#f8fafc] px-3 py-2 text-[12px] text-[#6b7280]">
                  No files uploaded yet.
                </div>
              ) : (
                <div className="grid max-h-[220px] gap-2 overflow-y-auto pr-1">
                  {uploads.map((u) => (
                    <div key={u.id} className="flex items-center justify-between rounded-[12px] border border-[#e3edee] bg-[#f8fafc] px-3 py-2">
                      <div className="flex items-center gap-2 overflow-hidden">
                        <FileText size={14} className="shrink-0 text-[#6b7280]" />
                        <span className="truncate text-[13px] text-[#111827]">{u.name}</span>
                      </div>
                      <div className="shrink-0">
                        {u.status === 'uploading' && <Loader2 size={14} className="animate-spin text-[#1c69d4]" />}
                        {u.status === 'ready' && <CheckCircle2 size={14} className="text-[#10b981]" />}
                        {u.status === 'failed' && <AlertCircle size={14} className="text-[#ef4444]" />}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {uploadError ? (
            <div className="mt-3 flex gap-3 rounded-[16px] border border-amber-200 bg-amber-50 p-3 text-amber-800">
              <AlertCircle size={16} className="shrink-0" />
              <div className="text-[12px]">{uploadError}</div>
            </div>
          ) : null}

          {extractionJob?.status === 'failed' && (
            <div className="mt-3 flex gap-3 rounded-[16px] bg-red-50 p-4 text-red-700">
              <AlertCircle size={18} className="shrink-0" />
              <div className="text-[13px]">{extractionJob.error_message}</div>
            </div>
          )}
          {(extracting || extractionLogs.length > 0) && (
            <div className="mt-3 rounded-[16px] border border-[#e3edee] bg-white p-3">
              <div className="text-[11px] font-mono uppercase tracking-[0.14em] text-[#6b7280]">
                {extracting ? `${extractionStage}...` : 'Latest extraction logs'}
              </div>
              <div className="mt-2 max-h-[130px] space-y-1 overflow-auto">
                {(extractionLogs.length ? extractionLogs : ['Waiting for extraction status...']).slice(-8).map((line) => (
                  <div key={line} className="text-[12px] text-[#374151]">{line}</div>
                ))}
              </div>
            </div>
          )}
        </section>

        <section className="rounded-[24px] border border-[rgba(0,0,0,0.08)] bg-[#faf9f4] p-4 shadow-sm md:p-5">
          <div className="mb-2 flex items-center gap-2">
            <Sparkles size={16} className="text-[#ff5c4b]" />
            <div className="text-[15px] font-semibold tracking-[0.02em]">Preview</div>
          </div>
          <div className={`border bg-[#070707] p-0 shadow-sm transition-all duration-700 ${recentlyExtracted ? 'border-[#1c69d4] ring-2 ring-[#1c69d4]/20' : 'border-[rgba(0,0,0,0.06)]'}`}>
            <div className="border-b border-white/10 px-5 py-3 text-white">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <div className="text-[12px] font-mono tracking-[0.08em] text-white/70">getdesign.md</div>
                  <div className="mt-1 text-[28px] font-semibold tracking-[-0.02em] text-white">{dna.theme || 'Brand DNA System'}</div>
                  <div className="mt-1 max-w-[520px] text-[13px] leading-6 text-white/60">{dna.description || 'Upload assets above and this preview will refresh with the latest extracted brand DNA, guardrails, and visual language.'}</div>
                </div>
                {(recentlyExtracted || isPreviewDraft) && (
                  <div className="flex items-center gap-1.5 border border-[#1c69d4]/30 bg-[#1c69d4]/10 px-3 py-1 text-[11px] font-medium text-[#9fcbff]">
                    <Sparkles size={11} />
                    {isPreviewDraft ? 'Visual preview ready' : 'AI extracted'}
                  </div>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <button
                  onClick={() => setPreviewMode('live')}
                  className={`inline-flex items-center gap-1.5 border px-3 py-1.5 text-[11px] uppercase tracking-[0.08em] ${previewMode === 'live' ? 'border-white/30 bg-white/10 text-white' : 'border-white/10 text-white/60 hover:text-white'}`}
                >
                  <Eye size={12} />
                  Live Preview
                </button>
                <button
                  onClick={() => setPreviewMode('design-md')}
                  className={`inline-flex items-center gap-1.5 border px-3 py-1.5 text-[11px] uppercase tracking-[0.08em] ${previewMode === 'design-md' ? 'border-white/30 bg-white/10 text-white' : 'border-white/10 text-white/60 hover:text-white'}`}
                >
                  <FileText size={12} />
                  DESIGN.md
                </button>
                <button
                  onClick={() => setPreviewMode('detailed')}
                  className={`inline-flex items-center gap-1.5 border px-3 py-1.5 text-[11px] uppercase tracking-[0.08em] ${previewMode === 'detailed' ? 'border-white/30 bg-white/10 text-white' : 'border-white/10 text-white/60 hover:text-white'}`}
                >
                  <Sparkles size={12} />
                  Detailed System
                </button>
              </div>
            </div>

            <div className="bg-[#070707] p-4">
              {previewMode === 'live' ? (
                <>
                  <div className="mb-4 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Eye size={16} className="text-[#ff5c4b]" />
                      <div className="text-[15px] font-semibold tracking-[0.02em] text-white">Preview</div>
                    </div>
                    {extracting ? (
                      <div className="text-[11px] uppercase tracking-[0.12em] text-white/55">
                        {extractionStage}...
                      </div>
                    ) : null}
                  </div>

                  {Object.keys(tokens).length > 0 && (
                    <div className="mb-4 flex flex-wrap gap-1.5">
                      {Object.entries(tokens).map(([key, val]) => (
                        <div key={key} title={`${key}: ${val}`} className="flex flex-col items-center gap-1">
                          <div
                            className="h-7 w-7 rounded-full border border-white/20 shadow-sm"
                            style={{ background: val }}
                          />
                          <span className="font-mono text-[9px] text-white/45">{key.replace(/_/g, ' ').replace('accent ', '')}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  <div
                    className="overflow-hidden border border-[#e3e0db] bg-white"
                    style={{
                      color: tokens.primary || '#F5F5F1',
                      fontFamily: typo.body || 'system-ui',
                      minHeight: '520px',
                    }}
                  >
                    <div className="flex items-center justify-between border-b border-black/10 px-6 py-4 text-[#262626]">
                      <div className="text-[14px] font-semibold tracking-[0.08em] uppercase">{dna.theme || 'Design System'}</div>
                      <div className="flex items-center gap-6 text-[11px] uppercase tracking-[0.18em] text-[#757575]">
                        <span>Palette</span>
                        <span>Type</span>
                        <span>Components</span>
                        <span>Layout</span>
                      </div>
                    </div>
                    <div className="px-10 py-14" style={{ background: tokens.background || '#050505' }}>
                      {isDashboardStyle ? (
                        <>
                          <div className="mb-8 text-[10px] uppercase tracking-[0.25em]" style={{ color: tokens.muted || '#A1A19B' }}>
                            extracted interface pattern / dashboard composition
                          </div>
                          <div className="grid gap-3 md:grid-cols-12">
                            <div className="md:col-span-3 space-y-3">
                              <div className="border p-4" style={{ borderColor: `${tokens.border || '#2A2A2A'}66`, background: tokens.surface || '#111111' }}>
                                <div className="text-[10px] uppercase tracking-[0.18em]" style={{ color: tokens.muted }}>Today&apos;s Focus</div>
                                <div className="mt-2 text-5xl font-semibold" style={{ color: tokens.ink }}>1.8</div>
                              </div>
                              <div className="border p-4" style={{ borderColor: `${tokens.border || '#2A2A2A'}66`, background: tokens.surface || '#111111' }}>
                                <div className="text-[10px] uppercase tracking-[0.18em]" style={{ color: tokens.muted }}>Output Velocity</div>
                                <div className="mt-2 text-4xl font-semibold" style={{ color: tokens.ink }}>24</div>
                              </div>
                            </div>
                            <div className="md:col-span-6 border p-5" style={{ borderColor: `${tokens.border || '#2A2A2A'}66`, background: tokens.surface || '#111111' }}>
                              <div className="text-[11px] uppercase tracking-[0.18em]" style={{ color: tokens.muted }}>Aesthetic + Usability</div>
                              <h2
                                className="mt-4"
                                style={{
                                  fontFamily: typo.headings || 'system-ui',
                                  fontSize: '52px',
                                  fontWeight: 700,
                                  lineHeight: 0.95,
                                  letterSpacing: '-0.04em',
                                  color: tokens.ink || '#111827',
                                  textTransform: 'uppercase',
                                  maxWidth: '9ch',
                                }}
                              >
                                {dna.theme || 'Design System'}
                              </h2>
                              <p className="mt-5 max-w-[48ch]" style={{ color: tokens.muted || '#A1A19B', fontSize: '16px', lineHeight: 1.6 }}>
                                {dna.description || 'Data-centric modular dashboard language extracted from uploaded visual references.'}
                              </p>
                            </div>
                            <div className="md:col-span-3 space-y-3">
                              <div className="border p-4" style={{ borderColor: `${tokens.border || '#2A2A2A'}66`, background: tokens.surface || '#111111' }}>
                                <div className="text-[10px] uppercase tracking-[0.18em]" style={{ color: tokens.muted }}>Total Balance</div>
                                <div className="mt-2 text-4xl font-semibold" style={{ color: tokens.ink }}>1.592</div>
                              </div>
                              <div className="border p-4" style={{ borderColor: `${tokens.border || '#2A2A2A'}66`, background: tokens.surface || '#111111' }}>
                                <div className="text-[10px] uppercase tracking-[0.18em]" style={{ color: tokens.muted }}>Work-Life Balance</div>
                                <div className="mt-2 text-4xl font-semibold" style={{ color: tokens.ink }}>7.89</div>
                              </div>
                            </div>
                          </div>
                        </>
                      ) : (
                        <>
                          <div className="mb-8 text-[10px] uppercase tracking-[0.25em]" style={{ color: tokens.muted || '#A1A19B' }}>
                            design system / extracted brand dna
                          </div>
                          <h1
                            style={{
                              fontFamily: typo.headings || 'system-ui',
                              fontSize: '64px',
                              fontWeight: 700,
                              letterSpacing: '-0.05em',
                              lineHeight: 0.95,
                              color: tokens.ink || '#111827',
                              textTransform: 'uppercase',
                              maxWidth: '10ch',
                            }}
                          >
                            {dna.theme || 'Design System'}
                          </h1>
                          <p
                            className="mt-8 max-w-[56ch]"
                            style={{ color: tokens.muted || '#A1A19B', fontSize: '18px', lineHeight: 1.7 }}
                          >
                            {dna.description || 'This preview shows how the latest extracted Brand DNA becomes a readable design system and generation-ready visual language.'}
                          </p>
                          <div className="mt-10 flex gap-4">
                            <button className="border px-6 py-3 text-[12px] uppercase tracking-[0.18em]" style={{ borderColor: tokens.border, color: tokens.ink }}>
                              Explore System
                            </button>
                            <button className="px-6 py-3 text-[12px] uppercase tracking-[0.18em]" style={{ background: tokens.ink, color: tokens.background }}>
                              Read the Dossier
                            </button>
                          </div>
                          <div className="mt-16 grid gap-5 md:grid-cols-3">
                            {(['accent_blue', 'accent_emerald', 'accent_purple', 'primary'].filter((key) => tokens[key])).slice(0, 3).map((key) => (
                              <div key={key} className="border p-5" style={{ borderColor: `${tokens.border || '#2A2A2A'}66`, background: tokens.surface || '#111111' }}>
                                <div style={{ color: tokens.muted, fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.18em' }}>{key.replace('accent_', '')}</div>
                                <div className="mt-5" style={{ fontSize: '36px', fontWeight: 800, color: tokens[key] }}>Aa</div>
                                <div className="mt-3" style={{ fontSize: '12px', color: tokens.muted }}>{tokens[key]}</div>
                              </div>
                            ))}
                          </div>
                        </>
                      )}
                      {(dna.effects || []).length > 0 && (
                        <div className="mt-8 flex flex-wrap gap-2">
                          {(dna.effects || []).map((eff, i) => (
                            <span key={i} className="border px-3 py-1.5 text-[10px] uppercase tracking-[0.14em]" style={{ color: tokens.muted, borderColor: tokens.border }}>
                              {eff}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </>
              ) : previewMode === 'design-md' ? (
                <div className="border border-white/10 bg-[#f8f8f4] p-6 text-[#111111]">
                  <div className="mb-4 flex items-center justify-between border-b border-black/10 pb-3">
                    <div>
                      <div className="text-[12px] font-mono uppercase tracking-[0.12em] text-[#757575]">DESIGN.md</div>
                      <div className="mt-1 text-[16px] font-semibold tracking-[0.02em]">Generated Design Reference</div>
                    </div>
                    <div className="text-[11px] uppercase tracking-[0.12em] text-[#757575]">for visual generation</div>
                  </div>
                  <div className="prose prose-sm max-w-none prose-headings:tracking-tight prose-headings:text-[#111111] prose-p:text-[#3f3f46] prose-li:text-[#3f3f46] prose-strong:text-[#111111] prose-code:text-[#1c69d4] prose-code:before:content-none prose-code:after:content-none">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {designReadme || '# DESIGN.md\n\nNo generated design reference yet. Upload assets and run extraction to create one.'}
                    </ReactMarkdown>
                  </div>
                </div>
              ) : (
                <div className="border border-white/10 bg-[#131417] p-6 text-[#f4f4f5]">
                  <div className="mb-5 flex items-center justify-between border-b border-white/10 pb-3">
                    <div>
                      <div className="text-[12px] font-mono uppercase tracking-[0.12em] text-[#9ca3af]">Detailed Preview</div>
                      <div className="mt-1 text-[16px] font-semibold tracking-[0.02em] text-white">Design System View</div>
                    </div>
                    <div className="text-[11px] uppercase tracking-[0.12em] text-[#9ca3af]">Generated from extraction + guardrails</div>
                  </div>
                  <div className="space-y-8">
                    <section>
                      <h3 className="text-[13px] font-semibold uppercase tracking-[0.16em] text-[#c7cad1]">Color Palette</h3>
                      <div className="mt-3 grid gap-2 md:grid-cols-3">
                        {Object.entries(tokens).map(([key, val]) => (
                          <div key={key} className="border border-white/10 p-3">
                            <div className="text-[10px] uppercase tracking-[0.14em] text-[#9ca3af]">{key.replace(/_/g, ' ')}</div>
                            <div className="mt-2 h-10 border border-white/10" style={{ background: val }} />
                            <div className="mt-2 font-mono text-[11px] text-[#d1d5db]">{String(val)}</div>
                          </div>
                        ))}
                      </div>
                    </section>

                    <section>
                      <h3 className="text-[13px] font-semibold uppercase tracking-[0.16em] text-[#c7cad1]">Typography Rules</h3>
                      <div className="mt-3 border border-white/10 p-4">
                        <div className="text-[26px] leading-tight" style={{ fontFamily: typo.headings || 'system-ui' }}>Display 01</div>
                        <div className="mt-2 text-[14px] text-[#aeb4bf]" style={{ fontFamily: typo.body || 'system-ui' }}>
                          Body Long 01 — Build smarter workflows with AI and hybrid cloud solutions that scale.
                        </div>
                        <div className="mt-3 font-mono text-[11px] text-[#9ca3af]">
                          headings: {typo.headings || 'N/A'} | body: {typo.body || 'N/A'}
                        </div>
                      </div>
                    </section>

                    <section>
                      <h3 className="text-[13px] font-semibold uppercase tracking-[0.16em] text-[#c7cad1]">Predefined UX Suggestions</h3>
                      <div className="mt-3 grid gap-2">
                        {predefinedUxSuggestions.map((item) => (
                          <div key={item} className="border border-white/10 bg-white/[0.02] px-3 py-2 text-[13px] text-[#d1d5db]">{item}</div>
                        ))}
                      </div>
                    </section>
                  </div>
                </div>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
