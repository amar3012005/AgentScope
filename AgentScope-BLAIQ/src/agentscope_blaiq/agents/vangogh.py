from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Awaitable, Callable
from uuid import uuid4

from pydantic import BaseModel, Field
from agentscope.tool import Toolkit

from agentscope_blaiq.contracts.artifact import ArtifactSection, PreviewMetadata, VisualArtifact
from agentscope_blaiq.contracts.evidence import EvidencePack
from agentscope_blaiq.runtime.agent_base import BaseAgent


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


def _css_for_family(family: str, brand_dna: dict | None = None) -> str:
    base = _PITCH_DECK_CSS if family == "pitch_deck" else (_FINANCE_CSS if family == "finance_analysis" else _REPORT_CSS)
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
                "You are Vangogh, a world-class HTML/CSS presentation and report designer. "
                "You generate visually stunning, self-contained HTML sections. "
                "Use modern design: dark themes for pitch decks, clean whites for reports. "
                "Every section must contain REAL content from the brief — never placeholder text. "
                "Use the provided CSS classes; add inline styles only for section-specific overrides. "
                "Return ONLY the HTML fragment — no markdown fences, no explanation."
            ),
            **kwargs,
        )

    def build_toolkit(self) -> Toolkit:
        toolkit = Toolkit()
        toolkit.register_tool_function(
            self._artifact_contract,
            func_name="artifact_contract",
            func_description="Return the required visual artifact contract for AgentScope-BLAIQ.",
        )
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
        if is_hero:
            layout_hint = "Use <section class='slide hero-bg'>. Add a .tag label above the h1. Use h1.display for the headline. Include subheadline as p.lead."
        elif section.stats and len(section.stats) >= 2:
            layout_hint = "Use a .card-grid with one .card per stat. Each card: .stat for the number, .stat-label for the description. Follow with .bullet-list for the bullets."
        elif section.bullets and len(section.bullets) >= 3:
            layout_hint = "Use a .bullet-list (ul) for the bullets. Each li is one bullet. Add h2.section-title and a brief p.lead from the body."
        elif is_cta:
            layout_hint = "Minimalist full-slide. h2.section-title as the CTA headline. p.lead for supporting text. .cta-btn anchor for the action."
        else:
            layout_hint = "Use h2.section-title for the headline, p.lead for the body. If there are bullets, add a .bullet-list. Wrap evidence points in .evidence-block."

        prompt = f"""Generate the HTML for slide {section_number} of {total_sections} in a {family} presentation titled "{title}".

=== SECTION: {section.title} ===
PURPOSE: {section.purpose or section.objective}
{content_block}

=== LAYOUT INSTRUCTION ===
{layout_hint}
VISUAL INTENT: {section.visual_intent or "Clean, bold, evidence-backed"}

=== CSS CLASSES AVAILABLE ===
.slide, .hero-bg, h1.display, h2.section-title, p.lead, .tag,
.card-grid, .card, .stat, .stat-label,
.bullet-list (ul > li), .cta-btn, .evidence-block, .source-chip

=== RULES ===
1. Wrapper MUST be <section class="{slide_class}"> (add .hero-bg for hero sections)
2. Use EVERY content item above — do not drop any headline, bullet, stat, or body text
3. Body text must appear in full — do not summarise or truncate
4. No placeholder text — every word must come from the content block above
5. Inline style overrides allowed only for section-specific colours or spacing
6. Return ONLY the HTML fragment — no markdown, no explanation"""

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
            self._write_slides_data(workspace, slides_data)

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

    def _write_slides_data(self, workspace: Path, slides_data: dict) -> None:
        """Write the slides.json file into the workspace."""
        slides_path = workspace / "src" / "slides.json"
        slides_path.write_text(
            json.dumps(slides_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    async def _bundle_workspace(self, workspace: Path) -> str:
        """Install deps and bundle the React app to a single HTML file."""
        await self.log("Installing dependencies and bundling React app...", kind="status")

        # Install dependencies
        install_proc = await asyncio.create_subprocess_exec(
            "pnpm", "install", "--no-frozen-lockfile",
            cwd=str(workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            install_proc.communicate(), timeout=120,
        )
        if install_proc.returncode != 0:
            raise RuntimeError(f"pnpm install failed: {stderr.decode()[:500]}")

        await self.log("Dependencies installed. Bundling...", kind="status")

        # Run the bundle script
        bundle_script = workspace / "scripts" / "bundle.sh"
        bundle_proc = await asyncio.create_subprocess_exec(
            "bash", str(bundle_script),
            cwd=str(workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
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
                "title": slide.get("title") or slide.get("headline") or f"Slide {i + 1}",
                "purpose": slide.get("subtitle") or slide.get("body") or "",
                "headline": slide.get("headline") or slide.get("title") or "",
                "subheadline": slide.get("subheadline") or slide.get("subtitle") or "",
                "body": slide.get("body") or "",
                "bullets": slide.get("bullets", []),
                "stats": slide.get("items", []),
                "visual_intent": slide.get("type", ""),
                "cta": slide.get("cta_text") or "",
            })
        return {
            "title": slides_data.get("title", "BLAIQ Artifact"),
            "family": "pitch_deck",
            "section_plan": section_plan,
        }
