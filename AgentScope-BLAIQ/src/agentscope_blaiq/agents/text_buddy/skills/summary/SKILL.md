---
name: summary
description: Rules for composing research summaries.
---
# TextBuddy — Executive Summary / Brief Artifact Skill

## Artifact Type
Executive summary or brief — a structured, evidence-heavy document that distills
complex findings into actionable intelligence for decision-makers.

## Template Structure

Generate the summary with these sections in order:

### 1. Key Finding
- Open with the single most important conclusion in 1-2 sentences, bold.
- This is the "if you read nothing else" statement.
- Ground it in evidence immediately — cite the primary source with `[source:ID]`.
- Frame as a fact or recommendation, not as a question or observation.
- Example: "Customer acquisition cost increased 34% QoQ, driven by declining
  paid search conversion rates [source:WEB-12]."

### 2. Supporting Evidence
- Present 3-5 evidence items that substantiate the key finding.
- Structure each item as:
  - **Finding**: One-sentence summary of the evidence.
  - **Source**: `[source:ID]` — origin type (memory, document, web).
  - **Confidence**: High / Medium / Low based on source reliability and recency.
- Order by relevance to the key finding, not by source type.
- Include contradictory evidence if it exists — flag it as such and explain the discrepancy.
- Do not omit inconvenient findings — intellectual honesty builds trust.

### 3. Analysis
- Interpret the evidence in 2-3 paragraphs.
- Connect individual findings into a coherent narrative: what do they mean together?
- Identify patterns, trends, or causal relationships supported by the evidence.
- Quantify impact where possible: revenue implications, risk exposure, opportunity size.
- Distinguish between what the evidence proves, what it suggests, and what remains unknown.
- Use phrases like "Evidence indicates," "Data suggests," "Findings confirm" —
  match certainty language to evidence strength.
- If evidence is thin in critical areas, state the gap explicitly rather than speculating.

### 4. Recommendation
- Provide 2-4 specific, actionable recommendations.
- Structure each as:
  - **Action**: What to do, described concretely.
  - **Rationale**: Which evidence supports this action (cite IDs).
  - **Priority**: High / Medium / Low.
  - **Timeline**: When to act — specific date or timeframe.
- Order recommendations by priority (highest first).
- Each recommendation must trace back to evidence in the Supporting Evidence section.
- If the evidence does not clearly support a recommendation, say so — "Pending further
  data on X, we provisionally recommend Y."

## Formatting Rules

- Use clear section headings for scannability.
- Bold key numbers, names, and conclusions within body text.
- Keep the entire document to 1-2 pages (400-700 words).
- Use bullet points for evidence items and recommendations — not dense paragraphs.
- Tables are acceptable for comparative data if 3+ data points exist.

## Citation Rules

- Every factual claim must include an inline `[source:ID]` citation.
- Group multiple sources supporting one claim: `[source:MEM-3, source:WEB-7]`.
- If a finding comes from HITL answers, cite as `[source:HITL]`.
- Do not cluster citations at the end — place them immediately after the claim they support.
- If a section lacks citable evidence, flag it: "No evidence available for this dimension."

## Tone Rules

- Analytical and objective — present facts, not opinions.
- Write for senior stakeholders: concise, structured, no filler.
- Use third person unless HITL answers specify otherwise.
- Avoid hedging without cause — if evidence is strong, state conclusions confidently.
- Avoid superlatives ("best," "worst," "unprecedented") unless evidence supports them.

## Rules

- Never pad the summary to reach a length target — shorter and evidence-dense beats long and diluted.
- If the evidence pack is sparse, produce a shorter summary rather than speculating.
- Contradictory evidence must be presented, not hidden — decision-makers need the full picture.
- If HITL answers specify the audience (board, technical leads, investors), adjust
  depth and terminology accordingly.
- The summary must be self-contained — a reader should not need to consult the
  original evidence pack to understand the conclusions.
