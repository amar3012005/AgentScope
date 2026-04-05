# Slide Type Reference

Available slide types for slides.json:

## `hero`
Full-screen opening slide with gradient background.
Fields: `tag`, `headline`, `subheadline`, `body`
Use for: Opening/title slide, main value proposition

## `data_grid`
Grid of stat cards with numbers and labels.
Fields: `title`, `subtitle`, `items[]` (each: `value`, `label`, `source`)
Use for: Key metrics, KPIs, market size, traction numbers

## `bullets`
Titled section with bullet list.
Fields: `title`, `subtitle`, `bullets[]` (string array)
Use for: Key points, features, benefits, challenges, methodology

## `evidence`
Source-attributed evidence cards.
Fields: `title`, `items[]` (each: `finding`, `source`, `confidence`)
Use for: Research findings, proof points, validated claims

## `cta`
Centered call-to-action slide.
Fields: `headline`, `body`, `cta_text`, `cta_url`
Use for: Closing slide, next steps, investment ask

## `quote`
Large quote with attribution.
Fields: `quote`, `attribution`, `role`
Use for: Vision statements, customer testimonials, founder quotes

## Choosing Slide Types

- 3+ metrics? → `data_grid`
- 3-5 key points? → `bullets`
- Source-backed evidence? → `evidence`
- Opening statement? → `hero`
- Closing action? → `cta`
- Quote/testimonial? → `quote`
