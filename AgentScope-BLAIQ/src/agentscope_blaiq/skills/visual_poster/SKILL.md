---
name: visual_poster
description: Poster Visual Blueprint - Single-page poster layout with precise zone specification
target_agent: ContentDirector,VanGogh
phase: visual_orchestration
context: single_page_design
---

# Visual Blueprint: Poster

## ARTIFACT TYPE: Single-Page Visual Poster
## PHASE 1 ABSTRACT: Define content zones and logical hierarchy.
## PHASE 2 SYNTHESIS: Apply Brand DNA to every zone with pixel-level precision.

---

## Canvas Specification
- **Dimensions**: 1080 x 1920px (portrait, standard print/digital)
- **Safe Zone**: 60px inset on all four edges. No content outside.
- **Background**: Deep Slate (#0D1117) full bleed. No border.
- **Grid System**: 12-column grid, 20px gutters.

---

## Zone Layout (Top to Bottom)

### Zone 1: Header Bar (Y: 60px – 180px)
- **Logo**: Top-left anchor. Max width 220px. Vertically centered in bar.
- **Logo Position**: X=60px, Y=80px.
- **Tagline**: Top-right, same vertical center as logo. Font: `Outfit Light`, 18px, Slate-400 (#94A3B8).
- **Divider**: 1px horizontal line, full width, Y=180px, color Emerald-500/30% opacity.

### Zone 2: Hero Visual (Y: 180px – 780px)
- **Image**: Full-width, 600px tall. Object-fit: cover. Overlay: linear-gradient(to bottom, transparent 60%, #0D1117 100%).
- **Image Type**: Abstract technology + nature fusion (glassmorphism aesthetic).

### Zone 3: Headline Block (Y: 740px – 960px) [Overlaps Hero]
- **Primary Headline**: Font `Outfit Bold`, 72px, White (#FFFFFF). Line height 1.1. Max 2 lines.
- **Sub-headline**: Font `Outfit Regular`, 28px, Emerald-400 (#34D399). Margin-top: 16px.
- **Alignment**: Left-aligned. X padding: 60px.

### Zone 4: Body / Key Points (Y: 980px – 1480px)
- **Layout**: 2-column grid (each 480px wide, 60px gap).
- **Each Point**: Glassmorphism card. Background: rgba(255,255,255,0.05). Border: 1px solid rgba(255,255,255,0.1). Border-radius: 16px. Padding: 32px.
- **Icon**: Emerald-500, 32px, top of each card.
- **Point Title**: `Outfit SemiBold`, 22px, White.
- **Point Body**: `Outfit Regular`, 16px, Slate-300 (#CBD5E1). Max 3 lines.

### Zone 5: CTA Block (Y: 1500px – 1680px)
- **Button**: Centered. Background Emerald-500. Border-radius: 12px. Padding: 20px 60px.
- **Button Text**: `Outfit Bold`, 24px, White. Content: Action phrase (e.g., "Learn More").
- **URL / Handle**: Below button. Font `Outfit Light`, 16px, Slate-400. Centered.

### Zone 6: Footer Bar (Y: 1700px – 1860px)
- **Left**: Company name. Font `Outfit Regular`, 14px, Slate-500.
- **Right**: QR code placeholder (120x120px, rounded 8px).
- **Center**: Social icons (32px each, Slate-400, spaced 24px apart).
- **Divider**: 1px line at Y=1700px, same as header divider style.

---

## Typography Rules (Phase 2 Mandatory)
- **Headline font**: Outfit Bold
- **Body font**: Outfit Regular / Light
- **Monospace accents**: Roboto Mono (for stats or technical values only)
- **No system fonts** permitted.

## Color Palette (Phase 2 Mandatory)
- Background: #0D1117 (Deep Slate)
- Primary Accent: #34D399 (Emerald-400)
- Secondary Accent: #10B981 (Emerald-500)
- Text Primary: #FFFFFF
- Text Secondary: #CBD5E1 (Slate-300)
- Text Muted: #94A3B8 (Slate-400)
- Glass Surface: rgba(255,255,255,0.05)
- Glass Border: rgba(255,255,255,0.10)

## Micro-Interactions (Phase 2 Suggestions for Digital Version)
- Hero image: parallax scroll effect on digital display.
- CTA button: hover scale(1.04) + emerald glow shadow.
- Glass cards: hover border-color transitions to Emerald-500/40%.
