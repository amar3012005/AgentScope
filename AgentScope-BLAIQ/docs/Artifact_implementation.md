ARTIFACT WORKFLOW: Multi-Agent Research-to-Design Pipeline
Executive Summary
This strategy outlines how to build a production-grade multi-agent system for creating high-quality artifacts (pitch decks, posters, webpages, case studies, reports) using a research-focused, HITL-enabled, design-optimized workflow. Inspired by Kimi K2.5/K2.6 Agent Swarm paradigm and industry HITL best practices.
Core Insight: Don't design agents → design artifacts. Agents are orchestrators; artifacts are the deliverables that carry value.

Architecture Overview
USER BRIEF
    ↓
┌─────────────────────────────────────────────────────────────────┐
│                    RESEARCH PHASE (Agent Swarm)                 │
├─────────────────────────────────────────────────────────────────┤
│  • Deep Research Agent (parallel web search, synthesis)         │
│  • Competitive Analysis Agent (parallel analysis tasks)         │
│  • Trend & Insight Agent (market, audience, psychological)      │
│  • Source Compilation Agent (organize findings, citations)      │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│        HITL CHECKPOINT 1: Strategy Review & Approval            │
├─────────────────────────────────────────────────────────────────┤
│  ✓ Fact-checking by SME                                         │
│  ✓ Insight validation (is it true? is it NEW? is it RELEVANT?) │
│  ✓ Competitive positioning feedback                             │
│  ✓ Audience persona refinement                                  │
│  ✓ Message framework approval                                   │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│            OPTIMIZATION PHASE (Research Synthesis)              │
├─────────────────────────────────────────────────────────────────┤
│  • Structured Insights Agent (organize for persuasion)          │
│  • AIDA Mapping Agent (Attention→Interest→Desire→Action)        │
│  • Copy Framework Agent (headlines, hooks, CTAs)                │
│  • Visual Direction Agent (mood, aesthetic, color, tone)        │
│  • Brand DNA Integration Agent (voice, values, personality)     │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│      HITL CHECKPOINT 2: Creative Direction Approval             │
├─────────────────────────────────────────────────────────────────┤
│  ✓ Brand voice check (sounds like us?)                         │
│  ✓ Messaging clarity (does the argument flow?)                 │
│  ✓ Visual direction (brand-aligned, differentiated?)           │
│  ✓ Content structure (AIDA flow correct?)                      │
│  ✓ Sources & evidence prioritization                           │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│         DESIGN PHASE (Content Director + Visual Designer)       │
├─────────────────────────────────────────────────────────────────┤
│  Content Director Creates:                                       │
│  • Complete artifact specifications (slide-by-slide for decks)  │
│  • Headline, body, CTA copy (EVERY text element)                │
│  • Hierarchy & emphasis map (what dominates each frame?)        │
│  • Color palette & visual motifs (brand DNA enforced)           │
│  • Layout grid (structure, white space, asymmetry intent)       │
│  • Animation/interaction plan (if applicable)                   │
│  • Data visualizations specifications (charts, diagrams)        │
│                                                                  │
│  Visual Designer Executes Via:                                   │
│  • Code-driven design (React/HTML from specifications)          │
│  • Tool-assisted design (Figma → hand-coded refinement)         │
│  • Vision-to-code workflow (design reference → polished code)   │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│        HITL CHECKPOINT 3: Design Direction Proof                │
├─────────────────────────────────────────────────────────────────┤
│  ✓ Visual hierarchy correct? (can you read without thinking?)   │
│  ✓ Brand voice present in design? (color, type, motion)         │
│  ✓ All facts/claims properly attributed? (source visible?)      │
│  ✓ Call-to-action clear & compelling?                          │
│  ✓ Mobile-responsive & accessible?                             │
│  ✓ Meets performance targets (load time, animation smoothness) │
└─────────────────────────────────────────────────────────────────┘
    ↓
FINAL ARTIFACT (HTML/JSX/PDF/PPT)

Phase 1: Research Phase (Agent Swarm - Parallel Execution)
Goal
Extract high-quality, fact-checked, audience-relevant insights that become the foundation for persuasive messaging and visual direction.
Agents & Their Responsibilities
1.1 Deep Research Agent
Task: Comprehensive, multi-angle research on topic, market, audience psychology.
Input:

Topic/product to present
Target audience persona
Key message pillars (initial hypothesis)
Geographic/industry context

Parallel Research Tracks (run these simultaneously):

Trend & Market Context (news, growth rates, adoption patterns)
Competitive Landscape (5-8 direct competitors, their positioning, messaging)
Audience Psychology (pain points, aspirations, buying triggers, objection patterns)
Use Case & ROI Data (case studies, metrics, quantifiable benefits)
Regulatory/Industry Standards (compliance, standards, best practices)
Visual Trends (aesthetic direction in the category, design preferences)

Output Format (Structured JSON/Markdown):
json{
  "research_timestamp": "ISO-8601",
  "topic": "string",
  "key_findings": [
    {
      "finding": "statement",
      "source": "URL + publication",
      "confidence": "high/medium/low",
      "relevance_to_pitch": "why this matters",
      "can_quote": true/false
    }
  ],
  "audience_insights": {
    "primary_motivation": "string",
    "key_objections": ["array"],
    "decision_criteria": ["array"],
    "psychological_triggers": ["array"]
  },
  "competitive_positioning": {
    "competitor": "name",
    "positioning": "how they message it",
    "gap_vs_us": "opportunity"
  },
  "research_sources": ["URLs with confidence scores"],
  "gaps_identified": ["what we still need"]
}
1.2 Competitive Analysis Agent
Task: Deep dive on competitor positioning, messaging, visual identity, go-to-market angles.
Input:

Target competitors (5-8)
What to analyze (messaging, pricing, features, visual brand)

Analysis Tracks:

Positioning Matrix (where do they sit on market axes?)
Messaging Audit (headlines, taglines, hero copy, CTAs)
Feature/Benefit Framing (how they talk about features vs outcomes)
Social Proof Strategy (testimonials, case studies, metrics they highlight)
Visual Identity Breakdown (color, typography, photography style, mood)
Go-to-Market Motion (what channels? what's their hook?)

Output:
json{
  "competitor_profiles": [
    {
      "name": "Competitor X",
      "positioning": "one-liner",
      "primary_message": "main argument",
      "visual_identity": {
        "color_palette": ["colors"],
        "typography_style": "description",
        "imagery_style": "description"
      },
      "gaps_vs_opportunity": "where we differentiate"
    }
  ],
  "market_positioning_map": {
    "dimensions": ["professional/consumer", "simple/powerful"],
    "our_position": "description of where we sit uniquely"
  }
}
1.3 Insight Synthesis Agent
Task: Distill research into high-impact, credible insights ready for persuasion.
Input:

Raw research output from agents 1.1 & 1.2
Audience persona
Brand positioning (current)

Synthesis Process:

Fact Verification (cross-reference claims, mark certainty)
Insight Extraction (what's surprising? what's actionable?)
Audience Relevance Scoring (does this resonate with our buyer?)
Competitive Differentiation (how do we leverage this vs competitors?)
Evidence Hierarchy (order insights by: credibility, novelty, relevance)

Output (Tiered Insights):
TIER 1: BLOCKBUSTER INSIGHTS (surprising, data-backed, differentiating)
  • "Market growing 47% YoY; competitor X still at legacy approach"
  • Source: Gartner Q1 2026 + competitor audit
  • Why it matters: Shows market momentum + our forward-thinking angle

TIER 2: CREDIBILITY INSIGHTS (validate our approach, reassure buyer)
  • "91% of enterprises cite integration speed as deciding factor"
  • Source: Forrester VoC study + our customer interviews
  • Why it matters: Addresses key buyer concern; we win on this

TIER 3: PSYCHOLOGICAL INSIGHTS (remove friction, trigger action)
  • "Buyers fear wasting time on pilot that goes nowhere"
  • Source: Sales team feedback + support conversations
  • Why it matters: Reframe around outcomes (quick time-to-value)
1.4 Source Compilation Agent
Task: Organize all research into a searchable, citable, auditable knowledge base.
Outputs:

Source registry (URL, publication, date, quote/metric, confidence, usage rights)
Citation guide (MLA, APA, inline links)
Visual asset index (images that can be legally used)
Data visualization templates (for charts/graphs)
Quote library (pre-formatted, attributed quotes sorted by theme)


Phase 2: HITL Checkpoint 1 - Strategy Review
Role: Strategy Lead / Founder / Subject Matter Expert
Review Checklist
Accuracy & Sourcing

 All claims have verified sources (no hallucinations?)
 Data is current (last 3 months for trends, credible publication?)
 Competitive analysis reflects current reality (have they pivoted?)
 Pricing/features accurate (checked their website today?)

Relevance to Audience

 Does this research speak to our actual buyer? (not generic?)
 Insights address buyer's real pain points / aspirations?
 Positioning feels differentiated vs competitors?
 Message hierarchy makes sense (most important first?)

Believability

 Am I confident presenting these claims in a meeting?
 Would a critical customer push back on any of this?
 Evidence quality (analyst report > blog post > assumption?)

Brand Alignment

 Is the voice appropriate? (corporate vs scrappy vs academic?)
 Do insights position us in the market segment we want?
 Does this contradict anything we've previously claimed?

Feedback Format (if revision needed)
ISSUE: "Growth rate seems wrong"
TYPE: Accuracy / Relevance / Brand-fit
RESOLUTION: "Replace with Q1 2026 analyst report data"
PRIORITY: Critical / Important / Nice-to-have

APPROVED CHANGES:
[Human edits/clarifications → sent back to agents]
Approval Gate: ✓ Can proceed to Phase 3 once ALL critical issues resolved.

Phase 3: Optimization Phase (Content Strategy)
Goal
Transform verified research into persuasion framework, copy hooks, and visual direction that guides design.
Agents in This Phase
3.1 AIDA Mapping Agent
Task: Structure insights into proven persuasion flow.
AIDA Framework (for each artifact type):
A = ATTENTION (First 3 seconds)
   Goal: Stop the scroll, intrigue the skeptic
   Mechanics:
   • Surprise stat (market trend, customer win, your unique insight)
   • Visual hook (unexpected color, bold typography, motion)
   • Emotional resonance (aspiration, fear, belonging)
   
   Example: "91% of teams are still waiting 6+ weeks for data infrastructure"
   Why it works: specific number (credible), pain point (resonates), comparative (implies solution)

I = INTEREST (Next 10-30 seconds)
   Goal: Establish why this matters NOW
   Mechanics:
   • Urgency driver (market shift, competitive threat, deadline)
   • Stakes clarification (cost of inaction, missed opportunity)
   • Relevant context (their world, their challenge)
   
   Example: "AI adoption is accelerating. Teams without these capabilities will fall behind."
   Why it works: ties to audience's fear of obsolescence, implies we solve it

D = DESIRE (Minutes 1-3)
   Goal: Paint picture of better future
   Mechanics:
   • Vision statement (what's possible with solution?)
   • Social proof (credible users doing this, results achieved)
   • Specific outcomes (quantified benefits, ROI)
   
   Example: "Leading teams are cutting data setup from 6 weeks to 2 days."
   Why it works: tangible outcome, proof (case study), emotional payoff (relief, efficiency)

A = ACTION (Final 30 seconds)
   Goal: Remove friction from next step
   Mechanics:
   • Single, clear CTA (book demo, start free trial, get whitepaper)
   • Friction removal (no credit card, 30 min / "super easy")
   • Scarcity/urgency signal (limited slots, time-sensitive offer)
   
   Example: "Book a 20-min demo with our team. No credit card. This week only."
   Why it works: concrete, low-friction, feels exclusive (urgency)
Output: AIDA flow for each artifact slide/page/section
SLIDE 1: ATTENTION
  - Hook: "Market growing 47% YoY; 80% of teams still manual"
  - Visual: Bold stat + unexpected imagery
  - Duration: 3 seconds (speed = intrigue)

SLIDE 2: INTEREST
  - Message: "Why this matters: digital transformation is mandatory"
  - Evidence: 3-bullet risk statement + Gartner quote
  - Visual: Timeline showing competitive advantage gap

SLIDE 3-5: DESIRE
  - Outcomes: "See how [Customer] went from chaos to efficiency"
  - Proof: Case study, quantified metrics
  - Visual: Before/after comparison

SLIDE 6: ACTION
  - CTA: "Book your personalized demo"
  - Friction removal: "15 minutes, no setup required"
  - Visual: Clear button, urgency indicator (limited slots)
3.2 Messaging Framework Agent
Task: Distill AIDA flow into exact headline, subheadline, body copy, and CTA text.
Copy Specifications (what to generate):
For Pitch Deck:

Slide headlines (1 powerful sentence, not generic)
Slide subheaders (context/explanation)
Key bullet points (scannable, benefit-focused)
Speaker notes / talking points (what you say live)
Final CTA text

For Landing Page:

Hero headline (main promise)
Hero subheadline (clarification or urgency)
Hero CTA button text
Section headers (feature sections, testimonial headers)
Body copy for each section (scannable, benefit-driven)
Form labels & button text
Footer CTAs

For Poster:

Primary headline (bold, singular focus)
Secondary line (subtext, clarification)
CTA line (what to do)

Copy Principles:

Clarity: No jargon. If you can't explain it in plain language, rethink it.
Specificity: "47% faster" beats "much faster"
Benefit-focused: "Save 10 hours/week" beats "Automated workflow optimization"
Conversational: Write like you speak (contractions okay, no corporate-speak)
Action-oriented: Use verbs. "Discover," "Get," "Build," "Ship," not "Enable," "Facilitate," "Leverage"

Output: Line-by-line copy deck (every text element specified)
HEADLINE
"Ship features 3x faster with zero infrastructure setup"

SUBHEADLINE
"Leading teams are deploying in days, not months. Here's how."

BODY PARAGRAPH 1
"Your team has great ideas. What slows you down? Infrastructure overhead. 
Most platforms require weeks of setup and ongoing maintenance. 
We eliminated that. You get a fully managed, production-ready system. 
From idea to shipped: 2 days instead of 6 weeks."

CTA BUTTON
Primary: "Start Building Now" (urgency, action)
Secondary: "See How It Works" (low-friction alternative)
3.3 Brand DNA Integration Agent
Task: Ensure every word, color, visual choice reflects brand voice, values, personality.
Brand DNA Audit (Input required from user):

Brand voice guidelines (tone, vocabulary, taboo phrases)
Visual identity (color palette, typography choices, brand personality)
Competitive positioning (what do we stand for vs competitors?)
Brand values (what matters to us? authentic commitment?)
Audience relationship (are we the expert? peer? coach? disruptor?)

Integration Enforcement:
VOICE CHECKS
✓ Tone consistency: Does this sound like us? (check against brand examples)
✓ Vocabulary: No corporate clichés we'd never use
✓ Personality: Does it reflect our culture? (scrappy vs polished? serious vs playful?)

VISUAL DNA CHECKS
✓ Color usage: Primary colors in correct proportion? Secondary accents hit right moments?
✓ Typography: Font families match brand spec? Weights/sizes aligned?
✓ Imagery style: Photography style / illustration approach match brand?
✓ Layout philosophy: Do we prefer: minimalist/whitespace, structured/grid, organic/asymmetric?

POSITIONING CHECKS
✓ Market position defended: Does every claim reinforce our unique angle?
✓ vs competitors: Would our positioning be clear to a buyer comparing us side-by-side?
✓ Values visible: Can someone infer what we believe from this artifact?
Output: Brand compliance checklist + suggested refinements
PASS: ✓ Tone is conversational and benefit-focused (matches brand)
PASS: ✓ Color usage: 60% primary (blue), 30% secondary (orange), 10% accent
FLAG: ⚠ Photo style is corporate/generic; recommend lifestyle photography (matches our aesthetic better)
REVISION: "Leverage cutting-edge solutions" → "Ship faster" (our vocab)
3.4 Visual Direction Agent
Task: Define the aesthetic mood, color strategy, typography direction, and design motifs.
Visual Direction Specification (Output document):
AESTHETIC MOOD
Primary: "Ambitious but grounded" 
Explanation: We're not hype; we're confident. Not corporate; not scrappy.
Visual analogy: Apple product unveiling (polished, intentional) + startup energy (real people, modern)
Reference: Look at Figma's pitch deck, Superhuman's landing page, Linear's marketing site

COLOR PALETTE
Primary: Deep Blue (#0052CC)
  • Conveys trust, technology, stability
  • Used for: Headlines, primary buttons, key visuals

Secondary: Orange (#FF6B35)
  • Conveys energy, action, breakthrough
  • Used for: CTAs, highlight boxes, accent lines

Neutral: Charcoal (#1F2937) + Off-white (#F9FAFB)
  • For: Body text, backgrounds, negative space

Usage Rule: 60/30/10 split (60% neutral, 30% primary blue, 10% orange as accent)

TYPOGRAPHY
Display Font: "Clash Display" (geometric, confident, modern)
  • For: Headlines, primary messages
  • Weight: Bold (700) for impact, Medium (500) for subheads

Body Font: "Inter" (clean, readable, friendly)
  • For: Body text, labels, UI elements
  • Weight: Regular (400) for reading, Medium (500) for emphasis

Hierarchy Rules:
- Hero headline: 48px Clash Bold, primary blue
- Section headers: 32px Clash Medium, charcoal
- Body text: 16px Inter Regular, charcoal
- Labels: 14px Inter Medium, secondary gray

VISUAL MOTIFS
Motion: Subtle, purposeful
  • Fade-ins on scroll (200ms ease-in-out)
  • Slide transitions (300ms cubic-bezier)
  • No bouncy/playful animations (doesn't match brand)

Graphic Elements:
  • Geometric shapes (circles, triangles) representing growth/innovation
  • Grid-based layouts (structured, intentional)
  • Asymmetric composition (not boring grid, intentional offset)

Photography Style:
  • Real people, authentic moments (no stock photo look)
  • Diversity reflected naturally (team, customers)
  • Preferably lifestyle (people working, collaborating) vs isolated headshots
  • Color-treated (subtle blue/orange tint to match palette)

Iconography:
  • Outline style, 2px stroke weight
  • Geometric (matches primary aesthetic)
  • Consistent sizing (24px or 32px, not random)

DESIGN SYSTEM TOKENS
Spacing: 8px base unit (8, 16, 24, 32, 48, 64, 80)
Radius: 8px (modern, approachable, not sharp)
Shadows: Subtle (0 4px 12px rgba(0,0,0,0.1); not deep drama)

Phase 4: HITL Checkpoint 2 - Creative Direction Review
Role: Brand Lead / Creative Director / Founder
Approval Criteria
Message Clarity

 Can I explain this to a customer in one sentence?
 Does the headline stop me / make me curious?
 Does the AIDA flow make logical sense?
 Are benefits clear (not features listed)?

Brand Alignment

 This sounds like us (voice, tone, confidence level)?
 Color palette / visual direction reflect our identity?
 Positioning is clear and differentiated?

Persuasion Power

 Would THIS convince a skeptical buyer to take next step?
 Are the sources credible? (Would I cite them?)
 Does the evidence support the claim?

Feasibility

 Is the design direction achievable in timeline?
 Do we have the assets needed (photos, data, quotes)?
 Animation/interaction scope realistic?

Feedback Template
SECTION: Hero Headline
CURRENT: "Intelligent automation for modern teams"
ISSUE: Too generic; doesn't differentiate us
APPROVED REVISION: "Ship features 3x faster. No infrastructure overhead."
REASONING: Specific benefit, unique angle, speaks to buyer pain

APPROVAL: ✓ Proceed to design phase once these revisions complete

Phase 5: Design Phase
Role: Content Director + Visual Designer
5.1 Content Director Specifications (Pre-Design Handoff)
Deliverable: Complete artifact specification (so designer executes, doesn't interpret).
For Pitch Deck:
SLIDE 1: TITLE SLIDE
Headline: "Ship 3x Faster"
Subheadline: "No infrastructure overhead"
Body: [optional tagline]
CTA Button: "Let's Talk"
Visual Direction: Hero image (people collaborating, laptop visible)
Color Palette: Blue bg, orange accent
Special: Logo placement (top-left or bottom), confidentiality notice if needed

SLIDE 2: PROBLEM
Headline: "Most teams lose weeks to infrastructure"
Points:
  1. "Setup: typically 2-4 weeks" [source: Gartner]
  2. "Ongoing maintenance: 20% of team time" [source: customer data]
  3. "Complexity breeds errors & delays" [source: interview insights]
Visual: Before/after timeline (weeks vs days visual)
Chart Type: Horizontal bar chart (blue=old way, orange=our way)
Notes: Emphasize the WASTE, not just the pain

SLIDE 3: SOLUTION / HOW IT WORKS
Headline: "Here's how we changed that"
Flow Diagram: 
  [User] → [Our Platform] → [Ship in days]
  (3-step visual with icons)
Benefits listed:
  • Zero-setup deployment
  • Production-ready infrastructure
  • Built-in observability & scaling
Visual: Product screenshot (if available) OR conceptual diagram
Color: Neutral bg (white/gray), orange accents for arrows/highlights

SLIDE 4: PROOF / CASE STUDY
Headline: "See it in action"
Case Study: [Customer Name] (with permission)
  Company size: 150 engineers
  Challenge: "Database infrastructure slowing features"
  Result: "Deployed in 2 days; saved 6 weeks"
  Quote: "This just works. Our team can focus on product." — [Customer CTO]
Visual: Customer logo + before/after metric (6 weeks → 2 days)
Color: Neutral with orange stat highlight

SLIDE 5: COMPETITIVE POSITIONING (Optional)
Headline: "Why we're different"
Comparison:
  | Feature | Them | Us |
  | Setup time | 4 weeks | 2 days |
  | Support quality | Email ticket | Slack engineer |
  | Pricing | Complex, overage | Flat-rate, no surprises |
Visual: Simple comparison table (NOT a crowded matrix)
Tone: Factual, not smug

SLIDE 6: TEAM / CREDIBILITY
Headline: "Built by people who know this problem"
Bios: [Founder 1] — 10 years infrastructure eng @ [Big Company]
      [Founder 2] — 8 years product @ [High-Growth Startup]
Vision: "We believe infrastructure shouldn't slow innovation down."
Visual: Authentic team photo + logos of companies they've worked at
Color: Neutral, warm (humans should be focal point)

SLIDE 7: CALL-TO-ACTION
Headline: "Let's ship together"
CTA Primary: "Book a demo" (orange button)
CTA Secondary: "Explore docs" (text link)
Details: "20 mins. No credit card. This week."
Visual: Optional (could be abstract design, gradient, texture)
Color: Keep it simple (white bg, clear buttons)
For Landing Page:
HERO SECTION
H1: "Ship features 3x faster"
Subheading: "No infrastructure overhead"
Body copy: 1-2 sentence problem statement
CTA Button: "Start Building Now" (orange)
Visual: Hero image (collaborative, modern, people + tech)
Layout: Asymmetric (text left 40%, image right 60%)
Grid size: Full-width hero, 120px spacing left/right

SECTION 2: "THE PROBLEM"
Header: "Every day of delays costs you"
3-column layout:
  Col 1: Icon (hourglass), Headline "6+ weeks for setup", Body text
  Col 2: Icon (people), Headline "20% of team on infrastructure", Body text
  Col 3: Icon (warning), Headline "Fragile, manual, error-prone", Body text
Visual: Abstract icons (geometric style, blue/orange)
Layout: 3 equal columns, 32px gaps, left-aligned text

SECTION 3: "HOW IT WORKS"
Header: "Three steps to production"
3-step visual flow (horizontal):
  Step 1: "Connect" (icon) → Step 2: "Deploy" (icon) → Step 3: "Monitor" (icon)
Each step gets 1-line explanation
Visual: Custom icons (outline style), connecting arrows
Color: Blue/orange gradient arrows
Layout: Horizontal layout, center-aligned

SECTION 4: "PROOF"
Header: "Trusted by leading teams"
Logo grid: 4-6 customer logos (if available)
OR Case study card (1 featured customer):
  Customer: "Acme Corp"
  Stat: "From 6 weeks to 2 days"
  Quote: "This just works."
Visual: Logos in neutral gray (white text area if dark bg)
Layout: 2x3 grid or single featured card

SECTION 5: "FEATURES" (Optional)
Header: "What you get"
4-column feature grid:
  1. "Zero-setup" (description)
  2. "Production-ready" (description)
  3. "Built-in observability" (description)
  4. "Infinite scaling" (description)
Visual: Icons + light illustration per feature
Color: Neutral bg, orange highlights
Layout: Responsive 1-2-4 columns mobile/tablet/desktop

SECTION 6: "PRICING" (Optional)
Header: "Simple, transparent pricing"
Pricing tiers:
  Starter | Pro | Enterprise
  $29/mo | $99/mo | Custom
  Features listed per tier
CTA: "Choose plan" buttons (primary/secondary color)
Visual: Clean, minimal, focus on clarity

SECTION 7: "CTA / FOOTER"
Header: "Ready to ship faster?"
CTA Button: "Start Free Trial" (orange, large)
Secondary CTA: "Book a demo" (text link)
Social proof: "No credit card required | 14-day free trial"
Footer links: [Privacy] [Terms] [Blog] [Status]
Socials: [Twitter] [LinkedIn] [GitHub]
5.2 Visual Designer Execution
Input: Complete specifications from Content Director + Brand DNA
Execution Approach: Code-Driven Design (per Kimi K2.6 paradigm)

Translate specs to visual architecture:

Grid system (12-column, 8px baseline)
Component hierarchy (buttons, cards, headers)
Spacing & alignment rules
Animation triggers (scroll, hover, load)


Code production (choose based on artifact type):

Pitch Deck: React component library (export as PDF via headless browser)
Landing Page: React/Next.js with Tailwind CSS
Poster: SVG + HTML (print-ready export)
Case Study: Long-form HTML document (printable)


Design iteration loop:

Build slide/section as specified
Add micro-interactions (hover states, scroll reveals)
Refine spacing, typography weight, color saturation
Test responsiveness
A/B test if time permits (headline emphasis, CTA placement)


Quality gates:

 Spec adherence (every spec implemented, no liberties taken)
 Brand consistency (colors, fonts, voice apply throughout)
 Visual hierarchy clear (scannable in 3 seconds)
 Interaction smooth (animations feel polished, not janky)
 Performance acceptable (load time <3s, 60fps interactions)




Phase 6: HITL Checkpoint 3 - Design Direction Proof
Role: Founder / Marketing Lead / Executive Reviewer
Final Review Checklist
Visual Impact

 First impression: Does this stop me / make me lean in?
 Hierarchy: Can I scan in 10 seconds and know the story?
 Brand presence: Does this feel distinctly "us"?

Message Integrity

 Headline lands (is it compelling, or did we dilute it in design?)
 Copy is scannable (bullets work, not dense paragraphs?)
 Proof is credible (sources visible? numbers clear?)

Persuasion Mechanics

 AIDA flow works (Attention→Interest→Desire→Action progression clear?)
 CTA is obvious (button stands out, copy is action-oriented?)
 No friction (is it obvious what happens next?)

Technical Quality

 Load time acceptable (not slow?)
 Animations smooth (no jank, not distracting?)
 Mobile-responsive (works on phone, not broken?)
 Accessibility (alt text on images, colors pass WCAG?)

Competitive Differentiation

 Would a buyer see this and know we're NOT [competitor X]?
 Does our unique angle shine (or does it sound generic?)
 Are we confident presenting this to a skeptical customer?

Approval Decision
APPROVED: Artifact ready for deployment / presentation
REQUEST REVISIONS:
ISSUE: "CTA button isn't visible enough"
CHANGE: Make orange (currently gray) + increase size
TIMELINE: 1 hour

ISSUE: "The case study customer is our competitor"
CHANGE: Swap in [other customer] or anonymize
TIMELINE: 2 hours
MAJOR REWORK NEEDED: (rare)
REASON: "Message doesn't land; feels generic"
ACTION: Go back to Content Director, rework copy/visual direction

Implementation Modes
Mode 1: Sequential (Safer, More Controlled)
Research → HITL Checkpoint 1 ✓ → Optimization → HITL Checkpoint 2 ✓ → Design → HITL Checkpoint 3 ✓
Timeline: 2-3 weeks per artifact
Best for: High-stakes pitches (funding, C-suite comms)
Mode 2: Parallel with HITL Gates (Faster)
Research (parallel agents) ↓
                            HITL 1 ✓ (while design begins on parallel spec)
                            Optimization + Design (parallel) ↓
                                                      HITL 2 ✓ (feedback loops both)
                                                      Final Design ↓
                                                              HITL 3 ✓
Timeline: 1-2 weeks per artifact
Best for: Time-sensitive campaigns, multiple artifacts at once
Mode 3: Single-Pass (Kimi Agent Swarm Style)
All agents run in parallel:
  Research (5 agents) ↓
  + Optimization (4 agents) ↓
  + Design brief generation ↓
  → Visual Designer executes
  → HITL review (single checkpoint, high-touch fix)
  → Final artifact
Timeline: 3-5 days
Best for: High-velocity content (weekly blogs, social content, templates)
Risk: Requires strong brand guidelines, experienced designer, clear specs upfront

Tools & Tech Stack
Research Phase

Deep Research: Perplexity, You.com, native web search (parallel queries)
Competitive Analysis: SimilarWeb, Crunchbase, competitor websites, social listening
Synthesis: Claude (research synthesis), spreadsheets (data organization)

HITL Checkpoints

Collaboration: Google Docs (collaborative review), Slack (async feedback)
Approval: Loom (recorded feedback), Figma comments, GitHub issues

Optimization Phase

Copy: Claude (draft → iterate), Brand guidelines doc (enforcement)
Visual Direction: Figma (mood board creation), brand asset library

Design Phase

Code-Driven Design:

Pitch Decks: React + Tremor (charts) → Puppeteer (PDF export)
Landing Pages: Next.js + Tailwind CSS + Framer Motion
Posters: React + SVG + dynamic height calculation


Design Reference: Figma (if visual mockup needed before code)
Performance: Lighthouse (load time), Chrome DevTools (animation smoothness)

Delivery

Pitch Decks: PDF export (Keynote/PowerPoint native if needed)
Landing Pages: Deploy to Vercel/Netlify (live preview)
Posters: PNG/PDF export (print-ready)
Case Studies: PDF + web version


Quality Standards by Artifact Type
Pitch Deck

Slide count: 8-15 (not 40-slide monstrosity)
Time per slide: 1-2 minutes (pacing matters)
Copy density: Max 3 bullets per slide + headline
Visual diversity: No two consecutive slides with same layout
Animation: 1-2 per deck max (not every slide), meaningful transitions
Delivery ready: PDF + Keynote/PPT (speaker notes included)

Landing Page

Load time: <3s on 4G
Mobile-first: Primary design target is mobile, scales to desktop
Scroll depth: Key value proposition visible above fold
Conversion funnel: Clear progression from visitor → lead → customer
Copy length: Hero section <15 words; body <3 sentences per section
CTA buttons: Primary action obvious, secondary soft

Poster / Social Asset

File size: <500KB (optimized for web sharing)
Readable at small size: Typography hierarchy tested on phone thumbnail
Contrast: WCAG AA minimum (accessibility)
Call-out: Single focal point, clear hierarchy
Variants: Often 3-5 versions for A/B testing


Measuring Success
Pre-Artifact KPIs (Research)

Number of insights extracted
Source credibility scores (weighted by publication)
Competitive differentiation score (do we have a unique angle?)

Design KPIs

Design specification completeness (% of specs implemented)
Brand guideline adherence (color/type/voice consistency)
Visual hierarchy clarity (scanner test: 3-second understanding)

Post-Launch KPIs

Pitch Decks: Meeting booking rate (% of viewers who take next step)
Landing Pages: Conversion rate (visitors → leads), time-on-page, scroll depth
Posters/Social: Engagement rate (likes, clicks, shares), click-through rate

Qualitative Feedback

"Does this feel distinctly 'us'?" (internal brand alignment)
"Would I present this to a customer with confidence?" (credibility check)
"Did this change anyone's mind?" (persuasion effectiveness)


Common Pitfalls & How to Avoid
PitfallCauseFixArtifact feels genericNo differentiated insight; copied competitor messagingGo back to Phase 2 research; find the unique angle that only we haveHITL approval loop takes foreverUnclear criteria; bikeshedding; conflicting stakeholdersDefine approval criteria upfront; single decision-maker per checkpointDesign doesn't match specUnclear specifications; designer interpreted vs executedDetailed spec doc with examples; designer asks clarifying questions before buildingFacts/claims questioned in meetingWeak source citations; numbers out of dateEvery claim has visible attribution; sources pulled within 1 weekAnimation/motion makes it feel cheapOveruse; wrong pacing; doesn't match brand tone1-2 animations total; test on actual target device (not just desktop)Message gets diluted in designDesigner over-designed; spec wasn't specific enoughHeadline prominence enforced in spec; designer doesn't interpret copy hierarchyToo long to producePerfectionism; too many feedback loops; scope creepTime-box each phase; use templates for recurring artifact types; HITL decisions are final

Template Repository (Reusable)
Once you build one artifact well, create templates for future use:
Pitch Deck Template

React component library (slide templates)
Pre-formatted data visualization components
Approved color/font system
Speaker notes template

Landing Page Template

Section components (Hero, Features, Proof, CTA)
Form builder (email capture, demo booking)
Analytics integration (segment, mixpanel)
A/B testing setup (feature flags)

Poster Template

Responsive grid system
Typography preset hierarchy
Color swatches (quick apply)
Icon library (consistent style)


Example: Full Workflow for Pitch Deck (SaaS Company)
Scenario: Build a 10-slide pitch deck for Series A fundraising round.
Timeline: 2 weeks (Sequential mode)
Week 1, Day 1-2: Research Phase

Deep Research Agent: Market size, growth trends, customer pain points (target: VCs see growing market)
Competitive Agent: 6 competitors' pitches, positioning, how they framed problem
Synthesis: Extract 10 blockbuster insights, organized by AIDA

Week 1, Day 3: HITL Checkpoint 1

Founder reviews research, approves/revises insights
"This stat is old, replace with Q1 2026 data"
"Add this customer quote, it's powerful"
Gates approval: ✓ Research locked in

Week 1, Day 4-5: Optimization Phase

AIDA Mapping: Map research to persuasion flow (1 slide per element)
Copy Framework: Generate exact headline, subheadline, bullets for each slide
Brand DNA: Ensure tone matches company values (scrappy founder energy vs polished enterprise?)
Visual Direction: Define aesthetic (minimalist / maximalist? data-driven / emotional?)

Week 2, Day 1: HITL Checkpoint 2

CEO reviews messaging framework
"Headline is weak, make it punchy"
"Visual direction is too corporate, we're younger/scrappier"
Revisions completed, gates approval: ✓

Week 2, Day 2-4: Design Phase

Content Director: Writes final copy for each slide, specifies visuals (customer photos, chart types)
Visual Designer: Builds deck in React, exports to PDF
Iteration: 2-3 rounds of refinement (spacing, chart labels, animation timing)

Week 2, Day 5: HITL Checkpoint 3 & Launch

Founder / CMO final review (15 min spot check)
Deploy: Keynote version for presenting, PDF for distribution
Success: Deck ready for pitch meetings


Conclusion
This workflow elevates artifact creation from "throw it all together last-minute" to a disciplined, research-backed, persuasion-engineered process. The key:

Research first: Insights are the foundation; everything else follows.
HITL discipline: Humans catch hallucinations, enforce brand, ensure credibility.
Specification clarity: Designer executes specs, doesn't interpret messaging.
Speed option: Can run sequentially (safe) or parallel (fast) depending on stakes.
Artifact-first thinking: Agents serve the deliverable; not the other way around.

The workflow is scalable: Once templates exist, subsequent artifacts (same type) take 50% less time. Once a team internalizes this process, artifacts move from "gut-based" to "systematic," and quality becomes consistent.
