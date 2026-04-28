---
name: brand_dna
description: BLAIQ Visual Design System - Architectural Visual DNA with Solvis Design Tokens
target_agent: ContentDirector,VanGogh
phase: artifact_generation
context: design_foundation
---

### BLAIQ Visual DNA (UI/UX Guidelines)

Based on the strategic branding documents, design sketches, and the specific structure required by your "Architectural Visual DNA," here is the strict visual configuration file for the new Solvis brand identity.

***

### Architectural Visual DNA: Solvis Design Tokens

#### 1. Color System (Tokenized for Code)
*   **Primary Action Color (Energy Flows & Accents):** `#EA580C` (Tailwind `orange-600` / "Leuchtendes Orange"). Represents the glowing energy flows, warmth, and connectivity.
*   **Secondary/Support Color (Precision & Tech):** `#1E293B` (Tailwind `slate-800` / "Anthrazit"). Represents engineering precision, calmness, and the dark casing of the modular systems.
*   **Surface & Background Colors:** 
    *   *Light Mode:* `#F5F5F0` (Warm Sand/Beige / Tailwind `stone-50`) to create a sense of home, natural materials, and approachability.
    *   *Dark Mode / Premium Tech Sections:* `#0F172A` (Tailwind `slate-900`) for high-contrast, premium modular overviews.
*   **Semantic Colors:** 
    *   *Success:* `#10B981` (Emerald Green)
    *   *Warning:* `#F59E0B` (Amber)
    *   *Destructive:* `#E60000` (Classic Legacy Solvis-Rot for strict alerts).
*   **Color Ratio (60-30-10 Rule):** 60% Warm Sand/Beige (negative space, approachability), 30% Anthracite (typography, device casings, structured containers), 10% Glowing Orange (energy paths, primary buttons, highlights). Never flood the screen with orange; it must act as a precise, guiding energy line.

#### 2. Typography System (Hierarchy & Weights)
*   **Font Families:**
    *   *Display/Headers:* **Antenna** (Sans-serif).
    *   *Body/Paragraphs:* **Calibri** (Sans-serif).
*   **Weight Constraints:** All H1 and H2 headers must be `font-medium` or `font-bold` (Antenna Medium/Bold). Body text must always be `font-light` or `font-normal` (Calibri Regular) to maintain a clean, approachable reading experience.
*   **Tracking/Kerning:** Headers should use `tracking-tight` for a compact, premium, and structured architectural look, mirroring the physical precision of the hardware.

#### 3. Geometry, Borders, and Radii (Shape Logic)
*   **Border Radius:** The brand balances architectural precision with human warmth. Always use `rounded-2xl` for UI cards and containers (reflecting the smooth, modern casings of devices like the SolvisLeo). Use `rounded-full` for buttons and badges. Never use sharp `rounded-none` edges, paying homage to the classic circular "Solvis-Bogen".
*   **Borders:** Use subtle, warm borders `border border-stone-200` for light surfaces and `border-slate-700` for dark surfaces. Avoid heavy, harsh outlines.

#### 4. Material, Depth, and Texture
*   **Shadows:** Use soft, diffuse shadows (`shadow-xl shadow-stone-900/5` in light mode, or `shadow-orange-900/10` in dark mode) to lift UI elements gently off the background without feeling overly technical.
*   **Glassmorphism/Translucency:** Use minimalistic frosted glass (`bg-white/80 backdrop-blur-md`) to ensure the UI feels modern and lightweight, never dense or cluttered. 
*   **Gradients:** Gradients are central to the new Solvis aesthetic ("Wärmeverläufe"). Use subtle linear or radial heat gradients (`bg-gradient-to-br from-stone-100 to-orange-50` or dark mode `from-slate-900 to-slate-800` with soft orange underglows) to simulate flowing energy.

#### 5. Layout & Spacing
*   **Density:** Highly spacious ("Klarheit, Ruhe, Präzision"). Use extreme padding (`p-10`, `gap-8`) to let elements breathe. The layout must feel like a premium, calm living space, not a complex technical dashboard or a chaotic utility room.
*   **Alignment:** Always left-align text to maintain structured readability. Use distinct blocks to bundle USPs rather than scattering them.

#### 6. Imagery Directives (For Image Generation Prompts)
*   **Lighting Style:** "Soft, cinematic natural lighting," "Warm morning light / golden hour filtering through a window," "gedämpftes Licht" (subdued, cozy lighting).
*   **Color Grading:** "Warm, earthy tones with high contrast to sleek anthracite technology," "Subtle golden hour glow."
*   **Composition:** "Wide angle, moderate depth of field, minimalist composition, ample negative space, focus on human moments with technology seamlessly integrated in the background."
*   **Subjects:** "Real families or individuals experiencing everyday moments of comfort (drinking tea, reading), interacting happily and on equal footing with an SHK installer. Solvis devices (like the SolvisLeo with natural wood panels) placed harmoniously in a modern utility room or living space."
*   **Negative Prompt (Blacklist):** `--no cold lighting, sterile, messy cables, complex technical diagrams, crowded utility rooms, cartoon, 3d render, sad, chaotic, cheap, complicated.`
