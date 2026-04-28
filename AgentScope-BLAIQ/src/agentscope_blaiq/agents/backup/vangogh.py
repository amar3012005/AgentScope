from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import tempfile
from pathlib import Path
from typing import Awaitable, Callable
from uuid import uuid4

from pydantic import BaseModel, Field
from agentscope.tool import Toolkit

from agentscope_blaiq.contracts.brief import ArtifactBrief
from agentscope_blaiq.contracts.artifact import ArtifactSection, PreviewMetadata, VisualArtifact
from agentscope_blaiq.contracts.enforcement import enforcement_check
from agentscope_blaiq.contracts.evidence import EvidencePack
from agentscope_blaiq.contracts.messages import make_agent_input, make_agent_output
from agentscope_blaiq.runtime.agent_base import BaseAgent

logger = logging.getLogger(__name__)


class PlannedSection(BaseModel):
    section_id: str
    title: str
    purpose: str = ""
    objective: str = ""
    audience: str | None = None
    core_message: str = ""
    headline: str = ""
    subheadline: str = ""
    body: str = ""
    bullets: list[str] = Field(default_factory=list)
    stats: list[dict] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    visual_intent: str = ""
    cta: str = ""
    risks: list[str] = Field(default_factory=list)
    acceptance_checks: list[str] = Field(default_factory=list)


class PlannedContentBrief(BaseModel):
    title: str
    family: str = "custom"
    template_name: str = "default"
    narrative: str = ""
    audience: str | None = None
    core_message: str = ""
    visual_direction: str = ""
    cta: str = ""
    risks: list[str] = Field(default_factory=list)
    acceptance_checks: list[str] = Field(default_factory=list)
    section_plan: list[PlannedSection] = Field(default_factory=list)
    distribution_notes: list[str] = Field(default_factory=list)
    handoff_notes: list[str] = Field(default_factory=list)


_PITCH_DECK_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root { --bg: #0d0d14; --surface: #16162a; --surface2: #1e1e35; --accent: #6c63ff; --accent2: #ff6584; --text: #f0f0f8; --muted: rgba(240,240,248,0.6); --border: rgba(255,255,255,0.08); }
html { scroll-behavior: smooth; }
body { font-family: 'Inter', system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }
section.slide { min-height: 100vh; padding: clamp(48px, 8vw, 96px) clamp(32px, 10vw, 128px); display: flex; flex-direction: column; justify-content: center; border-bottom: 1px solid var(--border); position: relative; overflow: hidden; }
section.slide::before { content: ''; position: absolute; inset: 0; background: radial-gradient(ellipse 80% 60% at 50% -10%, rgba(108,99,255,0.15), transparent); pointer-events: none; }
h1.display { font-size: clamp(2.5rem, 6vw, 5rem); font-weight: 800; letter-spacing: -0.03em; line-height: 1.05; background: linear-gradient(135deg, #fff 40%, var(--accent)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
h2.section-title { font-size: clamp(1.8rem, 4vw, 3rem); font-weight: 700; letter-spacing: -0.02em; margin-bottom: 1.5rem; }
p.lead { font-size: clamp(1rem, 2vw, 1.3rem); color: var(--muted); max-width: 65ch; line-height: 1.75; margin-bottom: 1.5rem; }
.tag { display: inline-block; padding: 4px 14px; background: rgba(108,99,255,0.2); border: 1px solid rgba(108,99,255,0.4); border-radius: 100px; font-size: 0.8rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: var(--accent); margin-bottom: 1.5rem; }
.card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 20px; margin-top: 2rem; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 28px; position: relative; overflow: hidden; }
.card::after { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; background: linear-gradient(90deg, var(--accent), var(--accent2)); }
.stat { font-size: clamp(2rem, 5vw, 4rem); font-weight: 800; color: var(--accent); letter-spacing: -0.03em; }
.stat-label { font-size: 0.9rem; color: var(--muted); margin-top: 4px; }
.bullet-list { list-style: none; display: flex; flex-direction: column; gap: 12px; margin-top: 1.5rem; }
.bullet-list li { padding: 14px 20px; background: var(--surface); border-radius: 10px; border-left: 3px solid var(--accent); font-size: 1rem; line-height: 1.5; }
.cta-btn { display: inline-flex; align-items: center; gap: 10px; margin-top: 2.5rem; padding: 16px 40px; background: linear-gradient(135deg, var(--accent), #9b5de5); border-radius: 100px; font-size: 1.1rem; font-weight: 700; color: #fff; text-decoration: none; letter-spacing: 0.01em; box-shadow: 0 8px 32px rgba(108,99,255,0.4); }
.hero-bg { background: radial-gradient(ellipse 100% 80% at 50% 0%, rgba(108,99,255,0.25) 0%, transparent 60%); }
.evidence-block { background: var(--surface2); border-radius: 12px; padding: 20px 24px; margin-top: 12px; border: 1px solid var(--border); }
.source-chip { font-size: 0.75rem; color: var(--muted); padding: 3px 10px; border: 1px solid var(--border); border-radius: 100px; display: inline-block; margin-top: 8px; }
@media (max-width: 768px) { section.slide { padding: 40px 24px; } }
"""

_REPORT_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
:root { --bg: #f8f9fc; --surface: #ffffff; --accent: #1a56db; --accent2: #e74c3c; --text: #1a202c; --muted: #718096; --border: #e2e8f0; }
body { font-family: 'Inter', system-ui, sans-serif; background: var(--bg); color: var(--text); line-height: 1.7; }
.report-section { max-width: 860px; margin: 0 auto; padding: 64px 40px; border-bottom: 1px solid var(--border); }
h1 { font-size: 2.5rem; font-weight: 800; color: var(--text); letter-spacing: -0.02em; margin-bottom: 1rem; }
h2 { font-size: 1.75rem; font-weight: 700; color: var(--text); margin-bottom: 1rem; }
p { font-size: 1.05rem; color: var(--text); margin-bottom: 1rem; }
.kpi-row { display: flex; gap: 20px; flex-wrap: wrap; margin: 2rem 0; }
.kpi { flex: 1; min-width: 160px; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px; text-align: center; }
.kpi-value { font-size: 2.5rem; font-weight: 800; color: var(--accent); letter-spacing: -0.03em; }
.kpi-label { font-size: 0.85rem; color: var(--muted); margin-top: 4px; }
.hypothesis-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 24px; margin: 12px 0; border-left: 4px solid var(--accent); }
.verified { border-left-color: #38a169; }
.refuted { border-left-color: var(--accent2); }
.evidence-item { padding: 14px 0; border-bottom: 1px solid var(--border); }
.source { font-size: 0.8rem; color: var(--muted); margin-top: 4px; }
table { width: 100%; border-collapse: collapse; margin: 1.5rem 0; }
th { background: var(--accent); color: #fff; padding: 12px 16px; text-align: left; font-size: 0.9rem; }
td { padding: 12px 16px; border-bottom: 1px solid var(--border); font-size: 0.95rem; }
tr:nth-child(even) td { background: rgba(26,86,219,0.04); }
"""

_FINANCE_CSS = _REPORT_CSS + """
.thesis-block { background: linear-gradient(135deg, #1a1a2e, #16213e); color: #f0f0f8; border-radius: 16px; padding: 40px; margin: 2rem 0; }
.thesis-text { font-size: 1.5rem; font-weight: 700; line-height: 1.4; }
.risk-item { display: flex; gap: 16px; padding: 16px; background: #fff5f5; border-radius: 10px; border-left: 4px solid #e74c3c; margin: 8px 0; }
.recommendation-box { background: linear-gradient(135deg, #1a56db10, #1a56db05); border: 2px solid var(--accent); border-radius: 16px; padding: 32px; margin-top: 2rem; }
"""

# ─── PREMIUM POSTER DESIGN SYSTEM ────────────────────────────────────────────
# Full design token system: spacing scale, typography scale, color system,
# grid utilities, card components, contrast-enforced layout patterns.
# Each CSS custom property is named semantically so the LLM can reference them.
_POSTER_CSS = """
/* ── Reset ───────────────────────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; -webkit-font-smoothing: antialiased; }

/* ── Design Tokens ───────────────────────────────────────────────────────── */
:root {
  /* Color system — dark canvas, high-contrast hierarchy */
  --bg:           #080b14;
  --surface-1:    #0f1420;
  --surface-2:    #16203a;
  --surface-3:    #1d2d52;
  --border-subtle: rgba(255,255,255,0.07);
  --border-mid:    rgba(255,255,255,0.15);
  --border-bright: rgba(255,255,255,0.30);

  /* Text — strict contrast tiers (7:1 / 4.5:1 / 3:1) */
  --text-primary:   #f5f7ff;
  --text-secondary: rgba(245,247,255,0.72);
  --text-muted:     rgba(245,247,255,0.45);
  --text-inverse:   #080b14;

  /* Accent palette */
  --accent:         #4f8ef7;
  --accent-bright:  #7eb3ff;
  --accent-glow:    rgba(79,142,247,0.22);
  --accent-2:       #f76b4f;
  --accent-2-glow:  rgba(247,107,79,0.18);
  --success:        #3ecf8e;
  --warning:        #f5a623;

  /* Spacing scale — 8-point grid */
  --s-1:  4px;
  --s-2:  8px;
  --s-3:  12px;
  --s-4:  16px;
  --s-5:  24px;
  --s-6:  32px;
  --s-7:  48px;
  --s-8:  64px;
  --s-9:  96px;
  --s-10: 128px;

  /* Typography scale — fluid sizing */
  --t-xs:   clamp(0.7rem, 1vw, 0.8rem);
  --t-sm:   clamp(0.85rem, 1.3vw, 0.95rem);
  --t-base: clamp(1rem, 1.5vw, 1.1rem);
  --t-lg:   clamp(1.15rem, 2vw, 1.35rem);
  --t-xl:   clamp(1.4rem, 2.5vw, 1.75rem);
  --t-2xl:  clamp(1.8rem, 3.5vw, 2.5rem);
  --t-3xl:  clamp(2.5rem, 5vw, 3.75rem);
  --t-4xl:  clamp(3.5rem, 7vw, 5.5rem);
  --t-hero: clamp(4rem, 9vw, 7.5rem);

  /* Radius */
  --r-sm: 6px;
  --r-md: 12px;
  --r-lg: 20px;
  --r-xl: 28px;
  --r-pill: 9999px;

  /* Shadows */
  --shadow-card: 0 2px 16px rgba(0,0,0,0.45), 0 1px 4px rgba(0,0,0,0.3);
  --shadow-glow: 0 0 40px var(--accent-glow);
}

/* ── Base ────────────────────────────────────────────────────────────────── */
body {
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  background: var(--bg);
  color: var(--text-primary);
  line-height: 1.6;
  overflow-x: hidden;
}

/* ── Poster slide container ──────────────────────────────────────────────── */
section.poster-slide {
  position: relative;
  min-height: 100vh;
  padding: var(--s-9) clamp(var(--s-6), 10vw, var(--s-10));
  display: flex;
  flex-direction: column;
  justify-content: center;
  overflow: hidden;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg);
}

/* Ambient glow background — adds depth without hurting contrast */
section.poster-slide::before {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(ellipse 70% 50% at 15% 50%, rgba(79,142,247,0.1) 0%, transparent 60%),
              radial-gradient(ellipse 50% 40% at 85% 80%, rgba(247,107,79,0.07) 0%, transparent 55%);
  pointer-events: none;
}

/* Hero variant — full-bleed gradient top */
section.poster-slide.hero {
  background: linear-gradient(160deg, var(--surface-2) 0%, var(--bg) 60%);
}
section.poster-slide.hero::before {
  background: radial-gradient(ellipse 90% 70% at 50% -10%, rgba(79,142,247,0.2) 0%, transparent 65%);
}

/* Dark variant — slightly lighter surface */
section.poster-slide.dark { background: var(--surface-1); }

/* Accent variant — branded highlight section */
section.poster-slide.accent-section { background: var(--surface-2); }

/* ── Typography ──────────────────────────────────────────────────────────── */
/* Hero display — ultra-bold, max impact */
h1.poster-hero {
  font-size: var(--t-hero);
  font-weight: 900;
  letter-spacing: -0.04em;
  line-height: 0.95;
  color: var(--text-primary);
  max-width: 15ch;
}

/* Primary display headline */
h1.poster-display {
  font-size: var(--t-4xl);
  font-weight: 800;
  letter-spacing: -0.035em;
  line-height: 1.0;
  background: linear-gradient(135deg, var(--text-primary) 50%, var(--accent-bright) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  max-width: 18ch;
}

/* Section heading */
h2.poster-heading {
  font-size: var(--t-2xl);
  font-weight: 700;
  letter-spacing: -0.025em;
  line-height: 1.15;
  color: var(--text-primary);
  margin-bottom: var(--s-5);
}

/* Sub-heading */
h3.poster-subheading {
  font-size: var(--t-xl);
  font-weight: 600;
  letter-spacing: -0.015em;
  color: var(--text-primary);
  margin-bottom: var(--s-4);
}

/* Lead paragraph — supporting the headline */
p.poster-lead {
  font-size: var(--t-lg);
  color: var(--text-secondary);
  max-width: 55ch;
  line-height: 1.7;
  margin-top: var(--s-5);
}

/* Body text */
p.poster-body {
  font-size: var(--t-base);
  color: var(--text-secondary);
  max-width: 65ch;
  line-height: 1.8;
  margin-bottom: var(--s-4);
}

/* Eyebrow / category label above headline */
.poster-tag {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  padding: var(--s-2) var(--s-4);
  background: var(--accent-glow);
  border: 1px solid rgba(79,142,247,0.35);
  border-radius: var(--r-pill);
  font-size: var(--t-xs);
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--accent-bright);
  margin-bottom: var(--s-5);
}

/* Accent line — visual divider / section marker */
.accent-line {
  width: 48px;
  height: 4px;
  background: linear-gradient(90deg, var(--accent), var(--accent-2));
  border-radius: var(--r-pill);
  margin-bottom: var(--s-5);
}

/* ── Layout utilities ────────────────────────────────────────────────────── */
.poster-grid {
  display: grid;
  gap: var(--s-5);
  margin-top: var(--s-6);
}
.poster-grid.cols-2 { grid-template-columns: repeat(2, 1fr); }
.poster-grid.cols-3 { grid-template-columns: repeat(3, 1fr); }
.poster-grid.cols-4 { grid-template-columns: repeat(4, 1fr); }
.poster-grid.auto   { grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }

/* Split layout: 60/40 or 50/50 */
.poster-split {
  display: grid;
  grid-template-columns: 1.5fr 1fr;
  gap: var(--s-8);
  align-items: center;
}
.poster-split.equal { grid-template-columns: 1fr 1fr; }

/* Content column max-width */
.poster-col { max-width: 640px; }

/* ── Cards ───────────────────────────────────────────────────────────────── */
.poster-card {
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: var(--r-lg);
  padding: var(--s-6) var(--s-7);
  position: relative;
  overflow: hidden;
  box-shadow: var(--shadow-card);
  transition: border-color 0.2s;
}
/* Top accent bar — always present, color varies */
.poster-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--accent), var(--accent-2));
}

/* Stat card variant */
.poster-card.stat-card { text-align: center; padding: var(--s-7) var(--s-6); }

/* Highlighted card — glowing border */
.poster-card.highlighted {
  border-color: rgba(79,142,247,0.4);
  box-shadow: var(--shadow-card), var(--shadow-glow);
}

/* Evidence / quote card */
.poster-card.evidence {
  border-left: 3px solid var(--accent);
  border-top: none;
  border-radius: 0 var(--r-md) var(--r-md) 0;
  background: var(--surface-2);
}
.poster-card.evidence::before { display: none; }

/* ── Stats ───────────────────────────────────────────────────────────────── */
.poster-stat-big {
  font-size: var(--t-3xl);
  font-weight: 900;
  letter-spacing: -0.04em;
  color: var(--accent-bright);
  line-height: 1;
  display: block;
}
.poster-stat-label {
  font-size: var(--t-sm);
  color: var(--text-muted);
  font-weight: 500;
  margin-top: var(--s-2);
  letter-spacing: 0.02em;
  display: block;
}

/* ── Bullet list ─────────────────────────────────────────────────────────── */
.poster-bullets {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
  margin-top: var(--s-5);
}
.poster-bullets li {
  display: flex;
  gap: var(--s-3);
  align-items: flex-start;
  padding: var(--s-4) var(--s-5);
  background: var(--surface-1);
  border-radius: var(--r-md);
  border: 1px solid var(--border-subtle);
  font-size: var(--t-base);
  color: var(--text-secondary);
  line-height: 1.6;
}
.poster-bullets li::before {
  content: '';
  flex-shrink: 0;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  margin-top: 7px;
}

/* ── CTA elements ────────────────────────────────────────────────────────── */
.poster-cta-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--s-3);
  margin-top: var(--s-7);
  padding: var(--s-4) var(--s-8);
  background: var(--accent);
  border-radius: var(--r-pill);
  font-size: var(--t-base);
  font-weight: 700;
  color: #fff;
  letter-spacing: 0.02em;
  text-decoration: none;
  box-shadow: 0 8px 32px rgba(79,142,247,0.4);
}
.poster-cta-secondary {
  display: inline-flex;
  align-items: center;
  gap: var(--s-3);
  margin-top: var(--s-5);
  margin-left: var(--s-4);
  padding: var(--s-4) var(--s-7);
  background: transparent;
  border: 1px solid var(--border-mid);
  border-radius: var(--r-pill);
  font-size: var(--t-base);
  font-weight: 600;
  color: var(--text-secondary);
  text-decoration: none;
}

/* ── Source attribution ──────────────────────────────────────────────────── */
.source-chip {
  display: inline-block;
  padding: var(--s-1) var(--s-3);
  font-size: var(--t-xs);
  color: var(--text-muted);
  border: 1px solid var(--border-subtle);
  border-radius: var(--r-pill);
  margin-top: var(--s-2);
  margin-right: var(--s-2);
}

/* ── Utility ─────────────────────────────────────────────────────────────── */
.z-top { position: relative; z-index: 1; }
.text-accent { color: var(--accent-bright); }
.text-muted { color: var(--text-muted); font-size: var(--t-sm); }
.mt-sm { margin-top: var(--s-4); }
.mt-md { margin-top: var(--s-5); }
.mt-lg { margin-top: var(--s-7); }
.divider { height: 1px; background: var(--border-subtle); margin: var(--s-6) 0; }

/* ── Responsive ──────────────────────────────────────────────────────────── */
@media (max-width: 900px) {
  section.poster-slide { padding: var(--s-7) var(--s-6); }
  .poster-split { grid-template-columns: 1fr; gap: var(--s-6); }
  .poster-grid.cols-3 { grid-template-columns: repeat(2, 1fr); }
  .poster-grid.cols-4 { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 600px) {
  section.poster-slide { padding: var(--s-6) var(--s-5); }
  .poster-grid.cols-2, .poster-grid.cols-3, .poster-grid.cols-4 { grid-template-columns: 1fr; }
}
"""


def _css_for_family(family: str, brand_dna: dict | None = None) -> str:
    if family == "poster":
        base = _POSTER_CSS
    elif family == "pitch_deck":
        base = _PITCH_DECK_CSS
    elif family == "finance_analysis":
        base = _FINANCE_CSS
    else:
        base = _REPORT_CSS
    
    if not brand_dna:
        return base
    # Override CSS variables with brand DNA tokens
    tokens = brand_dna.get("tokens", {})
    typo = brand_dna.get("typography", {})
    overrides = []
    token_map = {
        "primary": "--text",
        "background": "--bg",
        "surface": "--surface",
        "border": "--border",
        "accent_blue": "--accent",
        "accent_purple": "--accent2" if family == "pitch_deck" else "--accent",
        "accent_emerald": "--accent2" if family != "pitch_deck" else "--accent",
        "muted": "--muted",
        "ink": "--text",
    }
    for dna_key, css_var in token_map.items():
        val = tokens.get(dna_key)
        if val:
            overrides.append(f"  {css_var}: {val};")
    if typo.get("headings"):
        overrides.append(f"  --brand-font-headings: {typo['headings']};")
    if typo.get("body"):
        overrides.append(f"  --brand-font-body: {typo['body']};")
    if not overrides:
        return base
    brand_root = ":root {\n" + "\n".join(overrides) + "\n}"
    font_override = ""
    if typo.get("headings"):
        font_override += f"\nh1, h1.display, h2, h2.section-title {{ font-family: {typo['headings']}; }}"
    if typo.get("body"):
        font_override += f"\nbody, p, p.lead, li {{ font-family: {typo['body']}; }}"
    return base + "\n/* Brand DNA overrides */\n" + brand_root + font_override


def _slide_class_for_family(family: str) -> str:
    if family == "poster":
        return "poster-slide"
    return "slide" if family == "pitch_deck" else "report-section"


def _is_usable_finding(f) -> bool:
    text = f.summary or ""
    if not text or len(text.strip()) < 20:
        return False
    if text.startswith("%PDF") or "\x00" in text:
        return False
    lower = text.lower()
    if "smoke test" in lower or "this file exists to verify" in lower:
        return False
    return True


def _top_findings_text(evidence: EvidencePack, max_items: int = 5) -> str:
    memory = [f for f in evidence.memory_findings if _is_usable_finding(f)]
    docs = [f for f in evidence.doc_findings if _is_usable_finding(f)]
    web = [f for f in evidence.web_findings if _is_usable_finding(f)]
    memory.sort(key=lambda f: f.confidence, reverse=True)
    all_f = memory + docs + web
    if not all_f:
        return "No structured findings available."
    lines = []
    for f in all_f[:max_items]:
        lines.append(f"- {f.title}: {f.summary[:200]}")
    return "\n".join(lines)


class VangoghAgent(BaseAgent):
    def __init__(self, **kwargs) -> None:
        super().__init__(
            name="VangoghAgent",
            role="vangogh",
            sys_prompt=(
                "You are the BLAIQ Visual Renderer (VanGogh). Your sole responsibility is to transform a "
                "structured ArtifactBrief into high-quality HTML/CSS artifacts.\n\n"
                "STRICT BOUNDARIES:\n"
                "• You DO NOT plan strategy or content hierarchy. Follow the ArtifactBrief exactly.\n"
                "• You DO NOT perform research. Use the evidence_refs provided.\n"
                "• You MUST honor the brand_dna and layout_hints in the brief.\n"
                "• Your output must be valid, production-ready HTML components."
            ),
            **kwargs,
        )

    def build_toolkit(self) -> Toolkit:
        toolkit = Toolkit()
        self.register_tool(toolkit, tool_id="artifact_contract", fn=self._artifact_contract, description="Return the required visual artifact contract for AgentScope-BLAIQ.")
        return toolkit

    def _artifact_contract(self):
        return self.tool_response(
            {
                "required_fields": ["artifact_id", "artifact_type", "title", "sections", "theme", "evidence_refs", "html", "css"],
                "section_fields": ["section_id", "section_index", "title", "summary", "html_fragment", "section_data"],
            }
        )

    @staticmethod
    def _parse_content_brief(content_brief: dict | None) -> PlannedContentBrief | None:
        if not content_brief:
            return None
        try:
            return PlannedContentBrief.model_validate(content_brief)
        except Exception:
            return None

    @staticmethod
    def _extract_html_fragment(raw: str) -> str:
        raw = raw.strip()
        raw = re.sub(r"^```(?:html)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
        return raw.strip()

    @staticmethod
    def _section_content_block(section: PlannedSection) -> str:
        """Format all rich content fields into a structured brief for the LLM."""
        lines = []
        if section.headline:
            lines.append(f"HEADLINE: {section.headline}")
        if section.subheadline:
            lines.append(f"SUBHEADLINE: {section.subheadline}")
        if section.body:
            lines.append(f"BODY TEXT:\n{section.body}")
        if section.bullets:
            lines.append("BULLET POINTS:")
            for b in section.bullets:
                lines.append(f"  • {b}")
        if section.stats:
            lines.append("KEY STATS:")
            for s in section.stats:
                lines.append(f"  {s.get('value', '')} — {s.get('label', '')}")
        if not lines:
            fallback = section.core_message or section.objective or section.purpose or section.title
            lines.append(f"CONTENT: {fallback}")
        if section.cta:
            lines.append(f"CTA: {section.cta}")
        return "\n".join(lines)

    async def _generate_section_html(
        self,
        section: PlannedSection,
        evidence: EvidencePack,
        family: str,
        section_number: int,
        total_sections: int,
        title: str,
    ) -> str:
        slide_class = _slide_class_for_family(family)
        content_block = self._section_content_block(section)
        is_hero = section_number == 1
        is_cta = section.title.lower() in {"cta", "ask", "call to action"}

        layout_hint = ""
        if family == "poster":
            if is_hero:
                layout_hint = (
                    "HERO LAYOUT — full-bleed cinematic opening.\n"
                    "Structure: .z-top wrapper → .poster-tag (category label) → h1.poster-display (headline, max 8 words) "
                    "→ p.poster-lead (one powerful sentence, max 20 words) → .poster-cta-btn (if CTA exists).\n"
                    "Add class 'hero' to the section element. Use var(--accent-glow) or var(--surface-2) backgrounds for depth."
                )
            elif section.stats and len(section.stats) >= 2:
                layout_hint = (
                    "STAT GRID LAYOUT — visual proof of scale.\n"
                    "Structure: .accent-line → h2.poster-heading (section title) → .poster-grid.auto (or .cols-3) "
                    "containing .poster-card.stat-card for each stat. Each card: span.poster-stat-big (the number) "
                    "+ span.poster-stat-label (what it means). If there are bullets, add .poster-bullets below the grid."
                )
            elif section.bullets and len(section.bullets) >= 3:
                layout_hint = (
                    "EVIDENCE LIST LAYOUT — structured proof points.\n"
                    "Structure: .poster-tag (optional) → .accent-line → h2.poster-heading → p.poster-lead (body teaser) "
                    "→ ul.poster-bullets (each li = one bullet). "
                    "If evidence_refs exist, add .source-chip elements after bullets."
                )
            elif is_cta:
                layout_hint = (
                    "CTA LAYOUT — action-focused close.\n"
                    "Structure: .poster-tag (urgency label) → h2.poster-heading (the ask, punchy) "
                    "→ p.poster-lead (supporting reason) → .poster-cta-btn (primary action) + optional .poster-cta-secondary. "
                    "Add class 'accent-section' to the section element."
                )
            else:
                layout_hint = (
                    "CONTENT LAYOUT — narrative body section.\n"
                    "Structure: .accent-line → h2.poster-heading → p.poster-lead → p.poster-body. "
                    "If multiple points, use .poster-grid.cols-2 with .poster-card.evidence for each point. "
                    "Wrap source attribution in .source-chip."
                )
        elif is_hero:
            layout_hint = "Use <section class='slide hero-bg'>. Add a .tag label above the h1. Use h1.display for the headline. Include subheadline as p.lead."
        elif section.stats and len(section.stats) >= 2:
            layout_hint = "Use a .card-grid with one .card per stat. Each card: .stat for the number, .stat-label for the description. Follow with .bullet-list for the bullets."
        elif section.bullets and len(section.bullets) >= 3:
            layout_hint = "Use a .bullet-list (ul) for the bullets. Each li is one bullet. Add h2.section-title and a brief p.lead from the body."
        elif is_cta:
            layout_hint = "Minimalist full-slide. h2.section-title as the CTA headline. p.lead for supporting text. .cta-btn anchor for the action."
        else:
            layout_hint = "Use h2.section-title for the headline, p.lead for the body. If there are bullets, add a .bullet-list. Wrap evidence points in .evidence-block."

        poster_design_rules = ""
        if family == "poster":
            poster_design_rules = """
=== POSTER DESIGN RULES (mandatory) ===
• CONTRAST: text-primary (#f5f7ff) on dark surfaces. NEVER use opacity < 0.45 for readable text.
• TOKENS: use CSS custom properties (var(--accent), var(--s-6), etc.) — no hardcoded hex except in gradient overrides.
• GRID: use .poster-grid.cols-N or .poster-split — no custom inline grid/flex layouts.
• DENSITY: max 3 content elements per card; max 5 bullets; max 4 stat cards per row.
• SPACING: sections need min padding-top/bottom var(--s-9). Cards need min padding var(--s-6).
• TYPOGRAPHY: only h1.poster-display OR h1.poster-hero per section (not both); follow with h2.poster-heading for sub-sections.
• VISUAL ANCHOR: every section MUST start with either .poster-tag, .accent-line, or a category eyebrow."""

        prompt = f"""Generate the HTML for section {section_number} of {total_sections} in a {family} visual titled "{title}".

=== SECTION: {section.title} ===
PURPOSE: {section.purpose or section.objective}
VISUAL INTENT: {section.visual_intent or "Bold, high-contrast, evidence-backed poster section"}
{content_block}
{poster_design_rules}
=== LAYOUT PATTERN ===
{layout_hint}

=== AVAILABLE CSS CLASSES ===
Poster layout: section.poster-slide[.hero|.dark|.accent-section], h1.poster-display, h1.poster-hero, h2.poster-heading, h3.poster-subheading, p.poster-lead, p.poster-body
Poster grid: .poster-grid[.cols-2|.cols-3|.cols-4|.auto], .poster-split[.equal], .poster-col
Poster cards: .poster-card[.stat-card|.highlighted|.evidence]
Poster stats: span.poster-stat-big, span.poster-stat-label
Poster bullets: ul.poster-bullets (li items)
Poster UI: .poster-tag, .accent-line, .poster-cta-btn, .poster-cta-secondary, .source-chip
Pitch/report: .slide, .hero-bg, h1.display, h2.section-title, p.lead, .tag, .card-grid, .card, .stat, .stat-label, .bullet-list, .cta-btn, .evidence-block
Utility: .z-top, .text-accent, .text-muted, .mt-sm, .mt-md, .mt-lg, .divider

=== HARD RULES ===
1. Outer wrapper: <section class="{slide_class} [variant]">
2. Use ALL content — every headline, bullet, stat, body text from the block above
3. Zero placeholders, zero lorem ipsum
4. Use ONLY CSS classes listed above — no custom class names
5. Return ONLY the HTML fragment — no markdown fences, no comments"""

        try:
            response = await self.resolver.acompletion(
                "vangogh",
                [
                    {"role": "system", "content": self.sys_prompt},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=3000,
                temperature=0.6,
            )
            raw = self.resolver.extract_text(response)
            return self._extract_html_fragment(raw)
        except Exception:
            # Fallback: use content block fields directly
            headline = section.headline or section.title
            body = section.body or section.core_message or section.objective or ""
            bullets_html = "".join(f"<li>{b}</li>" for b in section.bullets[:5])
            return (
                f'<section class="{slide_class}">'
                f'<h2 class="section-title">{headline}</h2>'
                + (f'<p class="lead">{section.subheadline}</p>' if section.subheadline else "")
                + (f'<p class="lead">{body}</p>' if body else "")
                + (f'<ul class="bullet-list">{bullets_html}</ul>' if bullets_html else "")
                + (f'<a class="cta-btn" href="#">{section.cta}</a>' if section.cta else "")
                + f'</section>'
            )

    async def generate(
        self,
        user_query: str,
        evidence: EvidencePack,
        content_brief: dict | None = None,
        on_section_ready: Callable[[ArtifactSection], Awaitable[None]] | None = None,
        brand_dna: dict | None = None,
    ) -> VisualArtifact:
        input_msg = make_agent_input(
            workflow_id=None,
            node_id="vangogh",
            agent_id="vangogh",
            payload={"user_query": user_query, "has_content_brief": bool(content_brief)},
            schema_ref="VangoghInput",
        )
        logger.debug("vangogh input_msg=%s", input_msg.msg_id)

        await self.log(
            f"Designing the visual artifact. Working with {len(evidence.citations)} evidence sources.",
            kind="status",
            detail={"source_count": len(evidence.citations), "has_content_brief": bool(content_brief), "has_brand_dna": bool(brand_dna)},
        )

        brief = self._parse_content_brief(content_brief)
        family = brief.family if brief else "custom"
        title = (brief.title if brief else None) or user_query.strip().rstrip(".")[:96]
        css = _css_for_family(family, brand_dna=brand_dna)

        # Build section plans from brief or fallback
        section_plans: list[PlannedSection] = brief.section_plan if brief and brief.section_plan else []
        if not section_plans:
            section_plans = [
                PlannedSection(
                    section_id="hero",
                    title="Overview",
                    purpose="Opening overview",
                    core_message=evidence.summary or user_query,
                    visual_intent="Bold headline and supporting context.",
                ),
                PlannedSection(
                    section_id="evidence",
                    title="Key Findings",
                    purpose="Present the main findings",
                    core_message="; ".join(f.summary for f in (evidence.memory_findings or [])[:3]),
                    visual_intent="Evidence cards with source attribution.",
                ),
            ]

        artifact_id = str(uuid4())
        sections: list[ArtifactSection] = []
        total = len(section_plans)

        for index, plan in enumerate(section_plans):
            section_title = plan.title or f"Section {index + 1}"
            await self.log(f"Rendering section {index + 1}: {section_title}", kind="status")

            html_fragment = await self._generate_section_html(
                section=plan,
                evidence=evidence,
                family=family,
                section_number=index + 1,
                total_sections=total,
                title=title,
            )

            summary = plan.headline or plan.core_message or plan.objective or plan.purpose or section_title
            section = ArtifactSection(
                section_id=plan.section_id or f"section-{index + 1}",
                section_index=index,
                title=section_title,
                summary=summary[:300] if summary else section_title,
                html_fragment=html_fragment,
                section_data={
                    "family": family,
                    "visual_intent": plan.visual_intent,
                    "objective": plan.objective or plan.purpose,
                    # Include CSS with first section so streaming preview has the right theme
                    **({"theme_css": css} if index == 0 else {}),
                },
            )
            sections.append(section)

            await self.log(
                f"{section_title} is now available in the live preview.",
                kind="artifact",
                detail={"section_id": section.section_id, "section_index": index},
            )

            # Stream section to preview immediately
            if on_section_ready is not None:
                await on_section_ready(section)

        # Enforce 1:1 section mapping: output sections must match plan sections
        plan_ids = [p.section_id for p in section_plans]
        output_ids = [s.section_id for s in sections]
        if plan_ids != output_ids:
            logger.warning(
                "vangogh section_map_mismatch: plan=%s output=%s",
                plan_ids, output_ids,
            )
            # In enforced mode this would block; in advisory mode just log
            enforcement_check(
                ok=(set(plan_ids) == set(output_ids)),
                errors=[f"Section map mismatch: plan has {plan_ids}, output has {output_ids}"]
                if set(plan_ids) != set(output_ids) else [],
                context="vangogh_section_map",
            )

        html = "\n".join([
            "<!doctype html>",
            "<html lang='en'>",
            "<head>",
            "  <meta charset='utf-8'>",
            "  <meta name='viewport' content='width=device-width, initial-scale=1'>",
            f"  <title>{title}</title>",
            "  <link rel='preconnect' href='https://fonts.googleapis.com'>",
            "  <link href='https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap' rel='stylesheet'>",
            f"  <style>{css}</style>",
            "</head>",
            "<body>",
            *(section.html_fragment for section in sections),
            "</body>",
            "</html>",
        ])

        await self.log(
            f"Artifact composed: {len(sections)} sections, HTML and CSS generated.",
            kind="artifact",
            detail={"artifact_id": artifact_id, "section_count": len(sections)},
        )

        output_msg = make_agent_output(
            input_msg=input_msg,
            payload={"artifact_id": artifact_id, "section_count": len(sections)},
            schema_ref="VisualArtifact",
        )
        logger.debug("vangogh output_msg=%s parent=%s", output_msg.msg_id, output_msg.parent_msg_id)

        return VisualArtifact(
            artifact_id=artifact_id,
            title=title,
            sections=sections,
            theme={"palette": family, "mood": brief.visual_direction if brief else "executive"},
            evidence_refs=[citation.source_id for citation in evidence.citations],
            html=html,
            css=css,
            preview_metadata=PreviewMetadata(
                theme_notes=[
                    f"Family: {family}",
                    brief.visual_direction if brief else "Executive layout",
                ]
            ),
        )

    # ------------------------------------------------------------------
    # React + shadcn/ui template pipeline
    # ------------------------------------------------------------------

    async def generate_from_slides(
        self,
        *,
        slides_data: dict,
        user_query: str,
        evidence: EvidencePack,
        brand_dna: dict | None = None,
        artifact_family: str = "pitch_deck",
        tenant_id: str = "default",
        on_progress: Callable[[str, float], Awaitable[None]] | None = None,
    ) -> VisualArtifact:
        """Generate a visual artifact by bundling a React+shadcn/ui template.

        This is the new pipeline path. Instead of generating HTML per-section
        via LLM calls, it:
        1. Copies the pre-built React template to a temp workspace
        2. Injects Brand DNA CSS variables
        3. Writes ``slides.json`` (from ContentDirector's ``plan_slides()`` output)
        4. Bundles the React app into a single ``bundle.html``
        5. Returns the bundled HTML as the artifact
        """
        async def _progress(message: str, percent: float) -> None:
            await self.log(message, kind="status", detail={"percent": percent})
            if on_progress is not None:
                await on_progress(message, percent)

        try:
            await _progress("Creating workspace from React template...", 0.0)
            workspace = self._create_workspace(tenant_id)

            await _progress("Injecting Brand DNA tokens...", 0.15)
            self._inject_brand_dna(workspace, brand_dna)

            await _progress("Writing slides data...", 0.25)
            self._write_slides_data(workspace, slides_data, artifact_family=artifact_family)

            await _progress("Installing dependencies and bundling...", 0.35)
            bundle_html = await self._bundle_workspace(workspace)

            await _progress("Building artifact envelope...", 0.90)
            artifact = self._build_artifact(bundle_html, slides_data, evidence)

            await _progress("Artifact ready.", 1.0)
            return artifact

        except Exception as exc:
            await self.log(
                f"React bundle pipeline failed ({exc}), falling back to LLM generation.",
                kind="warning",
                detail={"error": str(exc)},
            )
            # Fallback to the existing LLM-based generation path
            content_brief = self._slides_data_to_content_brief(slides_data)
            return await self.generate(
                user_query=user_query,
                evidence=evidence,
                content_brief=content_brief,
                brand_dna=brand_dna,
            )

    # --- workspace helpers ---------------------------------------------------

    def _create_workspace(self, tenant_id: str) -> Path:
        """Copy the React template to a temporary workspace."""
        template_dir = Path(__file__).parent.parent / "artifacts" / "template"
        if not template_dir.is_dir():
            raise FileNotFoundError(f"Template directory not found: {template_dir}")
        workspace = Path(tempfile.mkdtemp(prefix=f"blaiq-artifact-{tenant_id}-"))
        shutil.copytree(
            template_dir,
            workspace,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("node_modules", ".parcel-cache", "dist"),
        )
        # Symlink node_modules from the template (pre-installed in Docker)
        template_nm = template_dir / "node_modules"
        if template_nm.is_dir():
            workspace_nm = workspace / "node_modules"
            workspace_nm.symlink_to(template_nm)
        return workspace

    def _inject_brand_dna(self, workspace: Path, brand_dna: dict | None) -> None:
        """Inject Brand DNA CSS variables into the template's index.css."""
        if not brand_dna:
            return

        tokens = brand_dna.get("tokens", {})
        typo = brand_dna.get("typography", {})

        css_path = workspace / "src" / "index.css"
        if not css_path.exists():
            return
        css = css_path.read_text(encoding="utf-8")

        replacements: dict[str, str] = {
            "--brand-bg": tokens.get("background", "#050505"),
            "--brand-surface": tokens.get("surface", "#111111"),
            "--brand-border": tokens.get("border", "#2A2A2A"),
            "--brand-primary": tokens.get("primary", "#F5F5F1"),
            "--brand-accent": tokens.get("accent_blue", "#6c63ff"),
            "--brand-accent2": tokens.get("accent_purple", "#ff6584"),
            "--brand-muted": tokens.get("muted", "#A1A19B"),
            "--brand-ink": tokens.get("ink", "#E8E7E2"),
            "--brand-font-heading": typo.get("headings", "'Inter'"),
            "--brand-font-body": typo.get("body", "'Inter'"),
        }

        for var_name, value in replacements.items():
            css = re.sub(
                rf"({re.escape(var_name)}:\s*)[^;]+;",
                rf"\1{value};",
                css,
            )

        # Add Google Fonts @import for custom fonts
        font_import_lines: list[str] = []
        for font_key in ["headings", "body"]:
            font = typo.get(font_key, "")
            if font and font not in ("Inter", "system-ui", "sans-serif"):
                font_name = font.split(",")[0].strip().strip("'\"")
                font_import_lines.append(
                    f"@import url('https://fonts.googleapis.com/css2?family="
                    f"{font_name.replace(' ', '+')}:wght@400;600;700;800&display=swap');"
                )

        if font_import_lines:
            css = "\n".join(font_import_lines) + "\n" + css

        css_path.write_text(css, encoding="utf-8")

    def _write_slides_data(self, workspace: Path, slides_data: dict, *, artifact_family: str = "pitch_deck") -> None:
        """Write the slides.json file into the workspace."""
        payload = dict(slides_data)
        payload["layout"] = payload.get("layout") or ("poster" if artifact_family == "poster" else "slides")
        slides_path = workspace / "src" / "slides.json"
        slides_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _inject_download_handler(self, html: str) -> str:
        """Inject a download handler script into the HTML bundle.

        This enables the parent window to request PDF/PNG captures via postMessage.
        Uses CDN-loaded html2canvas and jsPDF libraries.
        Captures the currently visible slide based on scroll position.
        """
        download_script = """
    <script>
      // Download handler for PDF/PNG export - captures current visible slide
      window.addEventListener('message', async function(event) {
        if (event.data && event.data.type === 'capture') {
          const format = event.data.format;

          // Find the slide that's most visible (based on scroll position)
          const container = document.querySelector('[style*="overflow-x"]');
          if (!container) {
            console.error('Slide container not found');
            return;
          }

          const scrollLeft = container.scrollLeft;
          const slideWidth = container.clientWidth;
          const currentSlideIndex = Math.round(scrollLeft / slideWidth);
          const slideElement = container.querySelector(`[data-slide-index="${currentSlideIndex}"]`);

          if (!slideElement) {
            console.error('Current slide not found');
            return;
          }

          try {
            // Load html2canvas from CDN if not already loaded
            if (typeof window.html2canvas === 'undefined') {
              await new Promise((resolve, reject) => {
                const script = document.createElement('script');
                script.src = 'https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';
                script.onload = resolve;
                script.onerror = reject;
                document.head.appendChild(script);
              });
            }

            const canvas = await window.html2canvas(slideElement, {
              backgroundColor: '#050505',
              scale: 2,
              useCORS: true,
            });

            const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, -5);
            if (format === 'png') {
              const link = document.createElement('a');
              link.download = `slide-${currentSlideIndex + 1}-${timestamp}.png`;
              link.href = canvas.toDataURL('image/png');
              link.click();
            } else if (format === 'pdf') {
              // Load jsPDF from CDN if not already loaded
              if (typeof window.jspdf === 'undefined') {
                await new Promise((resolve, reject) => {
                  const script = document.createElement('script');
                  script.src = 'https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.2/jspdf.umd.min.js';
                  script.onload = resolve;
                  script.onerror = reject;
                  document.head.appendChild(script);
                });
              }
              const { jsPDF } = window.jspdf;
              const pdf = new jsPDF({
                orientation: 'landscape',
                unit: 'px',
                format: [canvas.width, canvas.height],
              });
              pdf.addImage(canvas.toDataURL('image/png'), 'PNG', 0, 0, canvas.width, canvas.height);
              pdf.save(`slide-${currentSlideIndex + 1}-${timestamp}.pdf`);
            }
          } catch (err) {
            console.error('Capture failed:', err);
          }
        }
      });
    </script>
"""
        # Inject before closing </head> tag
        if "</head>" in html:
            html = html.replace("</head>", download_script + "</head>")
        return html

    async def _bundle_workspace(self, workspace: Path) -> str:
        """Install deps and bundle the React app to a single HTML file."""
        env = {**__import__("os").environ, "CI": "true"}  # CI=true skips pnpm TTY prompts

        # Only run pnpm install if node_modules is missing or not a symlink
        nm_path = workspace / "node_modules"
        if not nm_path.exists():
            await self.log("Installing dependencies...", kind="status")
            install_proc = await asyncio.create_subprocess_exec(
                "pnpm", "install", "--no-frozen-lockfile",
                cwd=str(workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(
                install_proc.communicate(), timeout=120,
            )
            if install_proc.returncode != 0:
                raise RuntimeError(f"pnpm install failed: {stderr.decode()[:500]}")
            await self.log("Dependencies installed.", kind="status")
        else:
            await self.log("Using pre-installed dependencies.", kind="status")

        await self.log("Bundling React app...", kind="status")

        # Run the bundle script
        bundle_script = workspace / "scripts" / "bundle.sh"
        bundle_proc = await asyncio.create_subprocess_exec(
            "bash", str(bundle_script),
            cwd=str(workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(
            bundle_proc.communicate(), timeout=120,
        )
        if bundle_proc.returncode != 0:
            raise RuntimeError(f"Bundle failed: {stderr.decode()[:500]}")

        bundle_path = workspace / "bundle.html"
        if not bundle_path.exists():
            raise RuntimeError("bundle.html not generated")

        html = bundle_path.read_text(encoding="utf-8")
        html = self._inject_download_handler(html)
        await self.log(f"Bundle complete: {len(html)} bytes", kind="status")

        # Cleanup workspace
        shutil.rmtree(workspace, ignore_errors=True)

        return html

    def _build_artifact(
        self,
        bundle_html: str,
        slides_data: dict,
        evidence: EvidencePack,
    ) -> VisualArtifact:
        """Build the final VisualArtifact from the bundled HTML."""
        slides = slides_data.get("slides", [])
        sections: list[ArtifactSection] = []
        for i, slide in enumerate(slides):
            sections.append(ArtifactSection(
                section_id=f"slide-{i}",
                section_index=i,
                title=slide.get("title") or slide.get("headline") or f"Slide {i + 1}",
                summary=(
                    slide.get("body")
                    or slide.get("subtitle")
                    or slide.get("headline")
                    or ""
                ),
                html_fragment="",  # Full HTML is in bundle, not per-section
                section_data={"type": slide.get("type", "unknown")},
            ))

        return VisualArtifact(
            artifact_id=str(uuid4()),
            title=slides_data.get("title", "BLAIQ Artifact"),
            sections=sections,
            theme={
                "palette": "react-shadcn",
                "mood": slides_data.get("brand", "default"),
            },
            evidence_refs=[c.source_id for c in evidence.citations],
            html=bundle_html,
            css="",  # CSS is bundled inline
            preview_metadata=PreviewMetadata(
                theme_notes=[
                    "React+shadcn/ui artifact",
                    f"{len(slides)} slides",
                ],
            ),
        )

    @staticmethod
    def _slides_data_to_content_brief(slides_data: dict) -> dict:
        """Convert slides_data dict to a content_brief dict for the legacy path."""
        slides = slides_data.get("slides", [])
        section_plan: list[dict] = []
        for i, slide in enumerate(slides):
            section_plan.append({
                "section_id": f"slide-{i}",
                "title": slide.get("title") or slide.get("headline") or slide.get("headline") or f"Slide {i + 1}",
                "purpose": slide.get("subtitle") or slide.get("body") or "",
                "headline": slide.get("headline") or slide.get("title") or "",
                "subheadline": slide.get("subheadline") or slide.get("subtitle") or "",
                "body": slide.get("body") or "",
                "bullets": slide.get("bullets", []),
                "stats": slide.get("items", []) or slide.get("metrics", []),
                "visual_intent": slide.get("type", ""),
                "cta": slide.get("cta_text") or "",
            })
        return {
            "title": slides_data.get("title", "BLAIQ Artifact"),
            "family": "pitch_deck",
            "section_plan": section_plan,
        }
