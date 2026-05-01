# VisualArtifactPreview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current iframe-only `VisualArtifactPreview` with a structured media renderer that handles images and videos as first-class JSON objects — no layout jitter, no blocking, smooth Framer Motion polish.

**Architecture:** Backend `VisualArtifact` gains a typed `media` array. Frontend splits into three focused components: `MediaBlock` (single item + per-item state machine), `MediaGrid` (layout dispatch based on `layout_hints`), and a rewritten `VisualArtifactPreview` that composites HTML iframe sections and media blocks. WorkbenchComponents and workspace context thread the new `media` prop through the existing data pipeline.

**Tech Stack:** React 18, Framer Motion, Tailwind CSS, Lucide icons, existing palette/theme from `WorkbenchTheme.jsx`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `src/agentscope_blaiq/contracts/artifact.py` | Add `MediaItem` + `media: list[MediaItem]` to `VisualArtifact` |
| Create | `frontend/src/components/hivemind/app/pages/chat/workstation/workbench/MediaBlock.jsx` | Single image/video with idle→loading→ready/error state machine, skeleton, controls |
| Create | `frontend/src/components/hivemind/app/pages/chat/workstation/workbench/MediaGrid.jsx` | Layout dispatch: hero, grid, carousel, inline, stack |
| Rewrite | `frontend/src/components/hivemind/app/pages/chat/workstation/workbench/VisualArtifactPreview.jsx` | Top-level renderer — HTML iframe OR media blocks, keeps backward compat |
| Modify | `frontend/src/components/hivemind/app/pages/chat/workstation/workbench/WorkbenchComponents.jsx` | Thread `media` + `layoutHints` through `PreviewFrame` |
| Modify | `frontend/src/components/hivemind/app/pages/chat/workstation/BlaiqWorkstation.jsx` | Pass `media` + `layoutHints` from artifact state to `PreviewFrame` |
| Modify | `frontend/src/components/hivemind/app/shared/blaiq-workspace-context.jsx` | Extract `media` + `layout_hints` from `artifact_ready` and `workflow_complete` events |

---

## Task 1: Extend Backend MediaItem Schema

**Files:**
- Modify: `src/agentscope_blaiq/contracts/artifact.py`

This gives the backend a typed contract for media objects. Frontend will mirror this shape.

- [ ] **Step 1: Add `MediaItem` and update `VisualArtifact`**

Open `src/agentscope_blaiq/contracts/artifact.py` and replace its contents with:

```python
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class ArtifactSection(BaseModel):
    section_id: str
    section_index: int
    title: str
    summary: str
    html_fragment: str
    section_data: dict[str, str] = Field(default_factory=dict)


class PreviewMetadata(BaseModel):
    viewport: str = "desktop"
    format_hint: str = "visual_html"
    theme_notes: list[str] = Field(default_factory=list)


class MediaItem(BaseModel):
    """A single media asset in a VisualArtifact."""
    id: str
    type: Literal["image", "video"]
    src: str
    thumbnail_src: str | None = None          # video poster / image thumb
    width: int | None = None
    height: int | None = None
    aspect_ratio: str | None = None           # e.g. "16/9", "4/3", "1/1"
    mime_type: str = ""                        # e.g. "image/png", "video/mp4"
    duration_ms: int | None = None            # video only
    alt: str = ""
    caption: str = ""
    status: Literal["pending", "ready", "failed"] = "ready"
    generation_state: Literal["pending", "ready", "failed"] = "ready"


class LayoutHints(BaseModel):
    layout: Literal["hero", "grid", "carousel", "inline", "stack"] = "grid"
    hero_item_id: str | None = None           # which media item is the hero


class VisualArtifact(BaseModel):
    artifact_id: str
    artifact_type: str = "visual_html"
    title: str
    sections: list[ArtifactSection] = Field(default_factory=list)
    theme: dict[str, str] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    governance_status: str = "pending"
    html: str = ""
    css: str = ""
    media: list[MediaItem] = Field(default_factory=list)
    layout_hints: LayoutHints = Field(default_factory=LayoutHints)
    preview_metadata: PreviewMetadata = Field(default_factory=PreviewMetadata)


class TextArtifact(BaseModel):
    """Final text output produced by the TextBuddy agent."""
    artifact_id: str
    artifact_type: str = "text"
    family: str
    title: str
    content: str
    template_used: str = "default"
    brand_voice_applied: bool = False
    evidence_refs: list[str] = Field(default_factory=list)
    governance_status: str = "pending"
    metadata: dict[str, str] = Field(default_factory=dict)
    completion_summary: str = ""
```

- [ ] **Step 2: Verify Python import works**

```bash
cd /Users/amar/blaiq/AgentScope-BLAIQ
python -c "from agentscope_blaiq.contracts.artifact import MediaItem, LayoutHints, VisualArtifact; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/agentscope_blaiq/contracts/artifact.py
git commit -m "feat: add MediaItem and LayoutHints to VisualArtifact contract"
```

---

## Task 2: Build `MediaBlock` — Single Media Item Renderer

**Files:**
- Create: `frontend/src/components/hivemind/app/pages/chat/workstation/workbench/MediaBlock.jsx`

`MediaBlock` renders one `MediaItem`. It owns the per-item state machine (`idle→loading→ready|error`), reserves layout space using `aspect_ratio` or `width/height` to prevent jitter, shows a skeleton while loading, fades in when ready, and shows a retry card on error.

- [ ] **Step 1: Create `MediaBlock.jsx`**

```jsx
import React, { useState, useCallback, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Play, Pause, Volume2, VolumeX, Maximize2, RotateCcw, AlertTriangle, ZoomIn, X } from 'lucide-react';
import { palette } from '../WorkbenchTheme';

// ─── Aspect ratio helper ─────────────────────────────────────────────────────
function parseAspectRatio(ar, width, height) {
  if (ar) return ar;
  if (width && height) return `${width}/${height}`;
  return '16/9';
}

// ─── Skeleton ────────────────────────────────────────────────────────────────
function MediaSkeleton({ aspectRatio }) {
  return (
    <div
      className="w-full animate-pulse rounded-2xl overflow-hidden"
      style={{ aspectRatio, backgroundColor: palette.gridLines }}
    >
      <div className="h-full w-full bg-gradient-to-br from-stone-100 to-stone-50" />
    </div>
  );
}

// ─── Error card ───────────────────────────────────────────────────────────────
function MediaError({ aspectRatio, onRetry, alt }) {
  return (
    <div
      className="w-full flex items-center justify-center rounded-2xl border border-red-200/60 bg-red-50/40"
      style={{ aspectRatio }}
    >
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <AlertTriangle size={20} className="text-red-400" />
        <p className="text-[12px] text-red-500 font-medium">{alt || 'Media failed to load'}</p>
        <button
          onClick={onRetry}
          className="flex items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 text-[11px] font-medium text-red-600 border border-red-200 hover:bg-red-50 transition-colors"
        >
          <RotateCcw size={11} /> Retry
        </button>
      </div>
    </div>
  );
}

// ─── Image block ─────────────────────────────────────────────────────────────
function ImageBlock({ item, onExpand }) {
  const [loadState, setLoadState] = useState(
    item.generation_state === 'pending' ? 'pending' : 'loading'
  );
  const [retryKey, setRetryKey] = useState(0);
  const aspectRatio = parseAspectRatio(item.aspect_ratio, item.width, item.height);

  const handleLoad = useCallback(() => setLoadState('ready'), []);
  const handleError = useCallback(() => setLoadState('error'), []);
  const handleRetry = useCallback(() => {
    setLoadState('loading');
    setRetryKey(k => k + 1);
  }, []);

  if (loadState === 'pending') return <MediaSkeleton aspectRatio={aspectRatio} />;
  if (loadState === 'error') return <MediaError aspectRatio={aspectRatio} onRetry={handleRetry} alt={item.alt} />;

  return (
    <div
      className="relative w-full overflow-hidden rounded-2xl group cursor-zoom-in"
      style={{ aspectRatio }}
      onClick={() => onExpand?.(item)}
    >
      {loadState === 'loading' && (
        <div className="absolute inset-0">
          <MediaSkeleton aspectRatio={aspectRatio} />
        </div>
      )}
      <motion.img
        key={retryKey}
        src={item.src}
        alt={item.alt || ''}
        onLoad={handleLoad}
        onError={handleError}
        initial={{ opacity: 0 }}
        animate={{ opacity: loadState === 'ready' ? 1 : 0 }}
        transition={{ duration: 0.4, ease: 'easeOut' }}
        className="absolute inset-0 h-full w-full object-cover"
        loading="lazy"
        width={item.width || undefined}
        height={item.height || undefined}
      />
      {loadState === 'ready' && (
        <div className="absolute inset-0 bg-black/0 group-hover:bg-black/10 transition-colors duration-200 flex items-center justify-center">
          <ZoomIn size={20} className="text-white opacity-0 group-hover:opacity-80 transition-opacity drop-shadow" />
        </div>
      )}
    </div>
  );
}

// ─── Video block ─────────────────────────────────────────────────────────────
function VideoBlock({ item }) {
  const [loadState, setLoadState] = useState('loading');
  const [isPlaying, setIsPlaying] = useState(false);
  const [isMuted, setIsMuted] = useState(true);
  const [retryKey, setRetryKey] = useState(0);
  const videoRef = useRef(null);
  const aspectRatio = parseAspectRatio(item.aspect_ratio, item.width, item.height);

  const handleCanPlay = useCallback(() => setLoadState('ready'), []);
  const handleError = useCallback(() => setLoadState('error'), []);
  const handleRetry = useCallback(() => {
    setLoadState('loading');
    setIsPlaying(false);
    setRetryKey(k => k + 1);
  }, []);

  const togglePlay = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    if (isPlaying) { v.pause(); setIsPlaying(false); }
    else { v.play().then(() => setIsPlaying(true)).catch(() => {}); }
  }, [isPlaying]);

  const toggleMute = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    v.muted = !isMuted;
    setIsMuted(m => !m);
  }, [isMuted]);

  const handleFullscreen = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    if (v.requestFullscreen) v.requestFullscreen();
  }, []);

  if (loadState === 'error') return <MediaError aspectRatio={aspectRatio} onRetry={handleRetry} alt={item.alt} />;

  return (
    <div className="relative w-full overflow-hidden rounded-2xl group" style={{ aspectRatio }}>
      {loadState === 'loading' && (
        <div className="absolute inset-0 z-10">
          <MediaSkeleton aspectRatio={aspectRatio} />
        </div>
      )}

      <motion.div
        animate={{ opacity: loadState === 'ready' ? 1 : 0 }}
        transition={{ duration: 0.4 }}
        className="absolute inset-0"
      >
        <video
          key={retryKey}
          ref={videoRef}
          poster={item.thumbnail_src || undefined}
          onCanPlay={handleCanPlay}
          onError={handleError}
          onEnded={() => setIsPlaying(false)}
          muted={isMuted}
          playsInline
          preload="metadata"
          className="h-full w-full object-cover"
        >
          <source src={item.src} type={item.mime_type || 'video/mp4'} />
        </video>

        {/* Controls overlay */}
        <div className="absolute inset-0 flex flex-col justify-end bg-gradient-to-t from-black/40 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-200">
          <div className="flex items-center gap-2 px-4 pb-4">
            <button
              onClick={togglePlay}
              className="flex h-8 w-8 items-center justify-center rounded-full bg-white/20 backdrop-blur-sm text-white hover:bg-white/30 transition-colors"
            >
              {isPlaying ? <Pause size={14} /> : <Play size={14} />}
            </button>
            <button
              onClick={toggleMute}
              className="flex h-8 w-8 items-center justify-center rounded-full bg-white/20 backdrop-blur-sm text-white hover:bg-white/30 transition-colors"
            >
              {isMuted ? <VolumeX size={14} /> : <Volume2 size={14} />}
            </button>
            <div className="flex-1" />
            <button
              onClick={handleFullscreen}
              className="flex h-8 w-8 items-center justify-center rounded-full bg-white/20 backdrop-blur-sm text-white hover:bg-white/30 transition-colors"
            >
              <Maximize2 size={14} />
            </button>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

// ─── Lightbox ─────────────────────────────────────────────────────────────────
function Lightbox({ item, onClose }) {
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.2 }}
        className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/80 backdrop-blur-sm p-6"
        onClick={onClose}
      >
        <motion.div
          initial={{ scale: 0.92, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.92, opacity: 0 }}
          transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
          className="relative max-h-[90vh] max-w-[90vw]"
          onClick={e => e.stopPropagation()}
        >
          <img
            src={item.src}
            alt={item.alt || ''}
            className="max-h-[85vh] max-w-[90vw] rounded-2xl object-contain shadow-2xl"
          />
          {item.caption && (
            <p className="mt-3 text-center text-[13px] text-white/70">{item.caption}</p>
          )}
          <button
            onClick={onClose}
            className="absolute -right-3 -top-3 flex h-8 w-8 items-center justify-center rounded-full bg-white/20 text-white backdrop-blur-sm hover:bg-white/30 transition-colors"
          >
            <X size={14} />
          </button>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}

// ─── Public API ───────────────────────────────────────────────────────────────
export function MediaBlock({ item }) {
  const [lightboxItem, setLightboxItem] = useState(null);

  if (!item?.src) return null;

  return (
    <>
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: [0.25, 0.1, 0.25, 1] }}
        className="w-full"
      >
        {item.type === 'image'
          ? <ImageBlock item={item} onExpand={setLightboxItem} />
          : <VideoBlock item={item} />
        }
        {item.caption && (
          <p className="mt-2 text-center text-[12px] text-stone-400 font-light">{item.caption}</p>
        )}
      </motion.div>

      {lightboxItem && (
        <Lightbox item={lightboxItem} onClose={() => setLightboxItem(null)} />
      )}
    </>
  );
}
```

- [ ] **Step 2: Verify file exists**

```bash
ls -la /Users/amar/blaiq/AgentScope-BLAIQ/frontend/src/components/hivemind/app/pages/chat/workstation/workbench/MediaBlock.jsx
```

Expected: file listed with non-zero size.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/hivemind/app/pages/chat/workstation/workbench/MediaBlock.jsx
git commit -m "feat: add MediaBlock component with per-item state machine and lightbox"
```

---

## Task 3: Build `MediaGrid` — Layout Dispatcher

**Files:**
- Create: `frontend/src/components/hivemind/app/pages/chat/workstation/workbench/MediaGrid.jsx`

`MediaGrid` takes a `media` array and `layoutHints` object and renders the correct layout. It never decides content — that's `MediaBlock`'s job. It decides composition only.

- [ ] **Step 1: Create `MediaGrid.jsx`**

```jsx
import React from 'react';
import { motion } from 'framer-motion';
import { MediaBlock } from './MediaBlock';

const CONTAINER_VARIANTS = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.06 } },
};

// ─── Layout strategies ────────────────────────────────────────────────────────

function HeroLayout({ items, heroId }) {
  const hero = heroId ? items.find(i => i.id === heroId) : items[0];
  const rest = items.filter(i => i !== hero);
  return (
    <div className="flex flex-col gap-4">
      {hero && (
        <div className="w-full">
          <MediaBlock item={hero} />
        </div>
      )}
      {rest.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {rest.map(item => <MediaBlock key={item.id} item={item} />)}
        </div>
      )}
    </div>
  );
}

function GridLayout({ items }) {
  const cols = items.length === 1
    ? 'grid-cols-1'
    : items.length === 2
      ? 'grid-cols-2'
      : 'grid-cols-2 sm:grid-cols-3';
  return (
    <div className={`grid gap-3 ${cols}`}>
      {items.map(item => <MediaBlock key={item.id} item={item} />)}
    </div>
  );
}

function StackLayout({ items }) {
  return (
    <div className="flex flex-col gap-4">
      {items.map(item => <MediaBlock key={item.id} item={item} />)}
    </div>
  );
}

function InlineLayout({ items }) {
  return (
    <div className="flex flex-wrap gap-3">
      {items.map(item => (
        <div key={item.id} className="min-w-[160px] flex-1">
          <MediaBlock item={item} />
        </div>
      ))}
    </div>
  );
}

function CarouselLayout({ items }) {
  const [active, setActive] = React.useState(0);
  if (!items.length) return null;
  return (
    <div className="flex flex-col gap-3">
      <div className="w-full overflow-hidden rounded-2xl">
        <MediaBlock key={items[active].id} item={items[active]} />
      </div>
      {items.length > 1 && (
        <div className="flex items-center justify-center gap-2">
          {items.map((item, i) => (
            <button
              key={item.id}
              onClick={() => setActive(i)}
              className={`h-1.5 rounded-full transition-all duration-200 ${
                i === active ? 'w-6 bg-stone-700' : 'w-1.5 bg-stone-300'
              }`}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Public API ───────────────────────────────────────────────────────────────
export function MediaGrid({ media = [], layoutHints = {} }) {
  if (!media.length) return null;

  const layout = layoutHints?.layout || 'grid';
  const heroId = layoutHints?.hero_item_id || null;

  const body = (() => {
    switch (layout) {
      case 'hero':      return <HeroLayout items={media} heroId={heroId} />;
      case 'carousel':  return <CarouselLayout items={media} />;
      case 'stack':     return <StackLayout items={media} />;
      case 'inline':    return <InlineLayout items={media} />;
      default:          return <GridLayout items={media} />;
    }
  })();

  return (
    <motion.div
      variants={CONTAINER_VARIANTS}
      initial="hidden"
      animate="visible"
      className="w-full"
    >
      {body}
    </motion.div>
  );
}
```

- [ ] **Step 2: Verify file exists**

```bash
ls -la /Users/amar/blaiq/AgentScope-BLAIQ/frontend/src/components/hivemind/app/pages/chat/workstation/workbench/MediaGrid.jsx
```

Expected: file listed with non-zero size.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/hivemind/app/pages/chat/workstation/workbench/MediaGrid.jsx
git commit -m "feat: add MediaGrid layout dispatcher (hero/grid/carousel/inline/stack)"
```

---

## Task 4: Rewrite `VisualArtifactPreview`

**Files:**
- Rewrite: `frontend/src/components/hivemind/app/pages/chat/workstation/workbench/VisualArtifactPreview.jsx`

The new component handles three cases:
1. **Media-only** — no HTML, has `media` array → render `MediaGrid` full-width
2. **HTML-only** — legacy path, `html` present, no `media` → render iframe (backward compat)
3. **Mixed** — `html` + `media` → render iframe for HTML body + `MediaGrid` below it

All three paths keep the toolbar (title, Live dot, copy button) consistent with `TextArtifactPreview`.

- [ ] **Step 1: Rewrite `VisualArtifactPreview.jsx`**

```jsx
import React, { useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Copy, CheckCircle2 } from 'lucide-react';
import { palette } from '../WorkbenchTheme';
import { MediaGrid } from './MediaGrid';

// ─── Normalise HTML for iframe ────────────────────────────────────────────────
function buildSrcDoc(html, css, title) {
  if (!html) return '';
  const extraCss = String(css || '').trim();
  const hasShell = /<!doctype html>|<html[\s>]/i.test(html) && /<body[\s>]/i.test(html);

  if (hasShell) {
    if (extraCss && /<\/head>/i.test(html)) {
      return html.replace(/<\/head>/i, `<style>${extraCss}</style></head>`);
    }
    return html;
  }

  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${title || 'Visual Artifact'}</title>
  <style>
    html, body { margin: 0; min-height: 100%; }
    body { background: #faf9f4; }
    ${extraCss}
  </style>
</head>
<body>${html}</body>
</html>`;
}

// ─── Toolbar ─────────────────────────────────────────────────────────────────
function Toolbar({ title, isLive, onCopy, copied }) {
  const statusLabel = isLive ? 'Rendering preview' : 'Artifact ready';
  return (
    <div
      className="sticky top-0 z-20 border-b"
      style={{ borderColor: palette.gridLines, backgroundColor: palette.cardSurface }}
    >
      <div className="flex items-center justify-between gap-3 px-6 py-5 sm:px-8 sm:py-6">
        <div className="min-w-0 flex-1">
          <h1 className="text-2xl font-bold tracking-tight text-stone-900 sm:text-3xl truncate">
            {title || 'Visual Artifact'}
          </h1>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <AnimatePresence mode="wait">
            {isLive && (
              <motion.span
                key="live"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="flex items-center gap-2 font-mono text-[9px] font-bold uppercase tracking-[0.18em]"
                style={{ color: palette.accentOrange }}
              >
                <span
                  className="h-1.5 w-1.5 animate-pulse rounded-full"
                  style={{ backgroundColor: palette.accentOrange }}
                />
                Live
              </motion.span>
            )}
          </AnimatePresence>
          <button
            onClick={onCopy}
            className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11px] font-medium transition-all"
            style={{ color: palette.mutedInk, backgroundColor: '#F7F6F2' }}
          >
            {copied
              ? <CheckCircle2 size={13} className="text-emerald-500" />
              : <Copy size={13} />
            }
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Public API ───────────────────────────────────────────────────────────────
export function VisualArtifactPreview({
  html = '',
  title = '',
  css = '',
  media = [],
  layoutHints = {},
  isLive = false,
}) {
  const [copied, setCopied] = useState(false);

  const hasHtml = Boolean(String(html || '').trim());
  const hasMedia = Array.isArray(media) && media.length > 0;

  const srcDoc = useMemo(
    () => (hasHtml ? buildSrcDoc(html, css, title) : ''),
    [html, css, title, hasHtml]
  );

  const handleCopy = async () => {
    try {
      const text = hasHtml ? html : media.map(m => m.src).join('\n');
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {}
  };

  // ── Case 1: media-only (no HTML) ───────────────────────────────────────────
  if (!hasHtml && hasMedia) {
    return (
      <div className="flex h-full w-full flex-col" style={{ backgroundColor: palette.panelSurface }}>
        <Toolbar title={title} isLive={isLive} onCopy={handleCopy} copied={copied} />
        <div className="flex-1 overflow-y-auto no-scrollbar px-6 py-8 sm:px-8">
          <div className="mx-auto max-w-4xl">
            <MediaGrid media={media} layoutHints={layoutHints} />
          </div>
        </div>
      </div>
    );
  }

  // ── Case 2: HTML-only (legacy, no media) ───────────────────────────────────
  if (hasHtml && !hasMedia) {
    return (
      <div className="flex h-full w-full flex-col" style={{ backgroundColor: palette.panelSurface }}>
        <Toolbar title={title} isLive={isLive} onCopy={handleCopy} copied={copied} />
        <div className="flex-1 overflow-hidden">
          <iframe
            title={title || 'Visual artifact preview'}
            srcDoc={srcDoc}
            className="h-full w-full border-0"
            sandbox="allow-same-origin allow-scripts"
          />
        </div>
      </div>
    );
  }

  // ── Case 3: mixed HTML + media ─────────────────────────────────────────────
  if (hasHtml && hasMedia) {
    return (
      <div className="flex h-full w-full flex-col" style={{ backgroundColor: palette.panelSurface }}>
        <Toolbar title={title} isLive={isLive} onCopy={handleCopy} copied={copied} />
        <div className="flex-1 overflow-y-auto no-scrollbar">
          <div className="h-[520px] w-full flex-shrink-0">
            <iframe
              title={title || 'Visual artifact preview'}
              srcDoc={srcDoc}
              className="h-full w-full border-0"
              sandbox="allow-same-origin allow-scripts"
            />
          </div>
          <div className="px-6 py-8 sm:px-8">
            <div className="mx-auto max-w-4xl">
              <MediaGrid media={media} layoutHints={layoutHints} />
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── Empty state ────────────────────────────────────────────────────────────
  return (
    <div className="flex h-full w-full items-center justify-center" style={{ backgroundColor: palette.panelSurface }}>
      <div className="flex flex-col items-center gap-4">
        <span className="h-8 w-8 animate-spin rounded-full border-2 border-stone-200 border-t-stone-900" />
        <span className="font-mono text-[9px] uppercase tracking-widest text-stone-400">
          {isLive ? 'Generating artifact...' : 'No content'}
        </span>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify no syntax errors by checking imports build**

```bash
cd /Users/amar/blaiq/AgentScope-BLAIQ/frontend
grep -n "from.*VisualArtifactPreview" src --include="*.jsx" --include="*.tsx" -r
```

Expected: lists `WorkbenchComponents.jsx` importing it.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/hivemind/app/pages/chat/workstation/workbench/VisualArtifactPreview.jsx
git commit -m "refactor: rewrite VisualArtifactPreview as structured media + HTML renderer"
```

---

## Task 5: Thread `media` and `layoutHints` Through `PreviewFrame`

**Files:**
- Modify: `frontend/src/components/hivemind/app/pages/chat/workstation/workbench/WorkbenchComponents.jsx:289-342`

`PreviewFrame` must accept and forward `media` + `layoutHints` to `VisualArtifactPreview`.

- [ ] **Step 1: Update `PreviewFrame` signature and call sites**

In `WorkbenchComponents.jsx`, find `PreviewFrame` (line ~289). Replace the function signature and both `PreviewComponent` call sites:

```jsx
export function PreviewFrame({
  id,
  html,
  title,
  isFullWindow = false,
  artifactPhase = null,
  css = null,
  markdown = null,
  media = [],
  layoutHints = {},
  onUpdate,
  isLive = false,
}) {
  const hasMarkdown = Boolean(String(markdown || '').trim());
  const hasHtml = Boolean(String(html || '').trim());
  const hasMedia = Array.isArray(media) && media.length > 0;
  const TEXT_PHASES = ['text_buddy', 'content_director', 'content_abstract'];
  const useTextPreview = TEXT_PHASES.includes(artifactPhase) || (hasMarkdown && !hasHtml);
  const PreviewComponent = useTextPreview ? TextArtifactPreview : VisualArtifactPreview;
  const content = useTextPreview ? markdown : html;
  const hasContent = useTextPreview ? hasMarkdown : (hasHtml || hasMedia);

  if (isFullWindow) {
    if (!hasContent && !useTextPreview) {
      return (
        <div className="flex h-full w-full items-center justify-center bg-[#F9F7F2]">
          <div className="flex flex-col items-center gap-4">
            <span className="h-8 w-8 animate-spin rounded-full border-2 border-stone-200 border-t-stone-900" />
            <span className="font-mono text-[9px] uppercase tracking-widest text-stone-400">Loading Render Core</span>
          </div>
        </div>
      );
    }
    return (
      <PreviewComponent
        id={id}
        html={content}
        title={title}
        css={css}
        media={media}
        layoutHints={layoutHints}
        isLive={isLive}
        onUpdate={onUpdate}
      />
    );
  }

  return (
    <div className="h-[520px] bg-white">
      {hasContent || useTextPreview ? (
        <PreviewComponent
          id={id}
          html={content || ''}
          title={title}
          css={css}
          media={media}
          layoutHints={layoutHints}
          markdown={markdown}
          isLive={isLive}
          onUpdate={onUpdate}
        />
      ) : (
        <div className="grid h-full place-items-center text-[12px] text-[#6E6A63]">
          <div className="rounded-xl border border-dashed border-[#ddd4c8] bg-[#faf7f2] px-4 py-3">
            Awaiting artifact preview...
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify `WorkbenchComponents.jsx` has no duplicate `PreviewFrame` definitions**

```bash
grep -n "export function PreviewFrame" /Users/amar/blaiq/AgentScope-BLAIQ/frontend/src/components/hivemind/app/pages/chat/workstation/workbench/WorkbenchComponents.jsx
```

Expected: exactly one match.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/hivemind/app/pages/chat/workstation/workbench/WorkbenchComponents.jsx
git commit -m "feat: thread media and layoutHints props through PreviewFrame"
```

---

## Task 6: Pass `media` and `layoutHints` from `BlaiqWorkstation`

**Files:**
- Modify: `frontend/src/components/hivemind/app/pages/chat/workstation/BlaiqWorkstation.jsx` (around line 345)

- [ ] **Step 1: Add `media` and `layoutHints` props to the `PreviewFrame` call**

Find the `<PreviewFrame` block (around line 345) and add two new props:

```jsx
<PreviewFrame
  id={activeTask?.artifact?.id}
  html={previewHtml}
  title={activeTask?.artifact?.title || previewTitle}
  isFullWindow
  isLive={activeTask?.status === 'running' || isSubmitting}
  artifactPhase={activeTask?.artifact?.phase}
  css={activeTask?.artifact?.css}
  markdown={activeTask?.artifact?.markdown}
  media={activeTask?.artifact?.media || []}
  layoutHints={activeTask?.artifact?.layoutHints || {}}
  onUpdate={(val) => activeTaskId && updateArtifact(activeTaskId, val)}
/>
```

- [ ] **Step 2: Verify diff is clean**

```bash
git diff frontend/src/components/hivemind/app/pages/chat/workstation/BlaiqWorkstation.jsx
```

Expected: only `media` and `layoutHints` lines added to the `PreviewFrame` block.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/hivemind/app/pages/chat/workstation/BlaiqWorkstation.jsx
git commit -m "feat: pass media and layoutHints from artifact state to PreviewFrame"
```

---

## Task 7: Extract `media` + `layoutHints` in Workspace Context

**Files:**
- Modify: `frontend/src/components/hivemind/app/shared/blaiq-workspace-context.jsx`

Two event handlers need updating: `artifact_ready` and `workflow_complete`. Both already set `updated.artifact`. We extend them to also persist `media` and `layoutHints`.

- [ ] **Step 1: Update `artifact_ready` handler**

Find the block at ~line 937:
```js
if (event.type === 'artifact_ready' && event.data?.artifact_manifest) {
  const manifest = event.data.artifact_manifest;
  updated.artifact = {
    id: manifest.artifact_id,
    title: manifest.title,
    sections: manifest.sections || [],
    theme: manifest.theme,
    html: manifest.html || '',
    css: manifest.css || '',
    phase: 'artifact',
  };
}
```

Replace with:
```js
if (event.type === 'artifact_ready' && event.data?.artifact_manifest) {
  const manifest = event.data.artifact_manifest;
  updated.artifact = {
    id: manifest.artifact_id,
    title: manifest.title,
    sections: manifest.sections || [],
    theme: manifest.theme,
    html: manifest.html || '',
    css: manifest.css || '',
    media: manifest.media || [],
    layoutHints: manifest.layout_hints || {},
    phase: 'artifact',
  };
}
```

- [ ] **Step 2: Update `workflow_complete` handler**

Find the block at ~line 950:
```js
if (event.type === 'workflow_complete' && event.data?.final_artifact) {
  const fa = event.data.final_artifact;
  updated.artifact = {
    id: fa.artifact_id,
    title: fa.title,
    sections: fa.sections || [],
    theme: fa.theme,
    html: fa.html || '',
    markdown: fa.markdown || '',
    css: fa.css || '',
    governance_status: fa.governance_status,
    phase: fa.phase || 'artifact',
  };
  ...
}
```

Replace the `updated.artifact = {...}` object with:
```js
updated.artifact = {
  id: fa.artifact_id,
  title: fa.title,
  sections: fa.sections || [],
  theme: fa.theme,
  html: fa.html || '',
  markdown: fa.markdown || '',
  css: fa.css || '',
  media: fa.media || [],
  layoutHints: fa.layout_hints || {},
  governance_status: fa.governance_status,
  phase: fa.phase || 'artifact',
};
```

- [ ] **Step 3: Verify both handlers were updated (no missed sites)**

```bash
grep -n "updated.artifact = {" /Users/amar/blaiq/AgentScope-BLAIQ/frontend/src/components/hivemind/app/shared/blaiq-workspace-context.jsx
```

Check each match — every one that handles a visual artifact phase should include `media:` and `layoutHints:`. Text-buddy/content-director blocks don't need it (they're text-only).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/hivemind/app/shared/blaiq-workspace-context.jsx
git commit -m "feat: extract media and layoutHints from artifact events in workspace context"
```

---

## Task 8: Smoke Test End-to-End

- [ ] **Step 1: Start the frontend dev server**

```bash
cd /Users/amar/blaiq/AgentScope-BLAIQ/frontend
npm run dev
```

Wait for `ready` in output.

- [ ] **Step 2: Test HTML-only path (backward compat)**

Trigger any existing visual artifact workflow. Confirm:
- Preview panel opens
- HTML renders in iframe as before
- No console errors about `media` or `layoutHints` props

- [ ] **Step 3: Test media-only path (manual mock)**

In browser devtools console, find the `BlaiqWorkspaceProvider` state and patch an artifact:
```js
// In React DevTools or console: set a task artifact with media only
// Expected: MediaGrid renders, no iframe shown
```

Or temporarily add to `BlaiqWorkstation.jsx` a hardcoded test fixture:
```jsx
// Temporary – remove after test
const testMedia = [
  { id: '1', type: 'image', src: 'https://picsum.photos/800/600', aspect_ratio: '4/3', alt: 'Test image', caption: 'Generated image', status: 'ready', generation_state: 'ready' },
  { id: '2', type: 'image', src: 'https://picsum.photos/800/450', aspect_ratio: '16/9', alt: 'Test 2', caption: '', status: 'ready', generation_state: 'ready' },
];
```

Pass `media={testMedia}` to `PreviewFrame` and verify:
- Grid layout renders 2 images
- Skeleton shows briefly then image fades in
- Click-to-expand opens lightbox
- ESC closes lightbox

- [ ] **Step 4: Test video path (manual mock)**

```jsx
const testVideo = [
  { id: 'v1', type: 'video', src: 'https://www.w3schools.com/html/mov_bbb.mp4', thumbnail_src: '', aspect_ratio: '16/9', mime_type: 'video/mp4', alt: 'Test video', caption: 'Test', status: 'ready', generation_state: 'ready' },
];
```

Verify:
- Skeleton shows while loading
- Video renders with poster frame
- Hover shows controls overlay
- Play/pause/mute/fullscreen work

- [ ] **Step 5: Remove any temporary test fixtures**

```bash
git diff frontend/src/components/hivemind/app/pages/chat/workstation/BlaiqWorkstation.jsx
```

Confirm no hardcoded `testMedia` / `testVideo` in diff.

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat: VisualArtifactPreview structured media renderer — complete"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** MediaBlock (Task 2) ✓, MediaGrid (Task 3) ✓, VisualArtifactPreview rewrite (Task 4) ✓, WorkbenchComponents thread (Task 5) ✓, BlaiqWorkstation thread (Task 6) ✓, workspace context extraction (Task 7) ✓, backend schema (Task 1) ✓
- [x] **No placeholders:** All tasks contain complete code, not descriptions
- [x] **Type consistency:** `media: MediaItem[]`, `layoutHints: LayoutHints` — same names used in Tasks 1–7
- [x] **Backward compat:** HTML-only iframe path preserved in VisualArtifactPreview Case 2
- [x] **No-jitter guarantee:** `aspect_ratio` used for skeleton sizing before image loads — layout stable
- [x] **No blocking:** Per-item state machine in MediaBlock, iframe remains independent
