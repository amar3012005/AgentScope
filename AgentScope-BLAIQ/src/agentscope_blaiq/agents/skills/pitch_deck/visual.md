# Pitch Deck — Visual Designer Skill

## Your Role
You are the visual designer rendering a pitch deck from slides.json data using React+shadcn components.

## Brand DNA Application
- Load Brand DNA CSS variables into :root
- ALL colors must use `brand-*` Tailwind classes (bg-brand-bg, text-brand-primary, etc.)
- Headings: `font-heading` class
- Body: `font-body` class
- NEVER use hardcoded colors — always reference brand tokens

## Layout Consistency Rules
- Every slide: `min-h-screen`, consistent horizontal padding `px-[clamp(2rem,10vw,8rem)]`
- Section transitions: consistent `py-24` vertical spacing
- Border radius: always `rounded-2xl` for cards, `rounded-full` for chips
- Card pattern: `bg-brand-surface border border-brand-border rounded-2xl p-7`

## Slide-Specific Components
- hero: Use gradient background from brand-accent/10, Badge for tag, display heading
- data_grid: 3-column grid on desktop, full-width cards on mobile
- bullets: Left-aligned list with accent border-left on each item
- evidence: Stacked cards with source chip at bottom
- cta: Centered layout, gradient CTA button
- quote: Centered with decorative quotation mark

## Anti-Slop Rules
- NO centered everything layouts (only hero and CTA are centered)
- NO purple gradients unless brand DNA specifies purple
- NO uniform rounded corners (use 2xl for cards, full for chips, 3xl for hero containers)
- NO generic placeholder text — every word comes from slides.json data
