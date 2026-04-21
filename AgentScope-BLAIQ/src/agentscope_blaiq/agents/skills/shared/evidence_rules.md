# Evidence Rules — Mandatory for ALL Artifact Generation

## CRITICAL: Content Generation Policy

1. **Use the provided evidence findings as your PRIMARY source material.** Extract facts, names, details, and claims from them.
2. **ALWAYS generate content for every section** — never write "Insufficient evidence." If the evidence doesn't perfectly match a section, use the CLOSEST relevant findings and adapt them to fit the section's purpose.
3. If evidence is sparse for a specific section, synthesize from what IS available — combine related findings, draw reasonable inferences, or use the user's HITL answers to fill gaps.
4. If the user's HITL answers provide direction, use those as the primary guide. Evidence supplements HITL answers.
5. When web findings and memory findings conflict, prefer memory findings (enterprise ground truth).
6. The findings may cover broad topics about the subject — use them creatively across sections. A finding about "architecture" can inform both "Solution" and "Proof" slides.

## Content Source Priority

1. **HITL answers** — user's explicit direction (highest priority)
2. **Memory findings** — HIVE-MIND enterprise knowledge
3. **Document findings** — uploaded tenant documents
4. **Web findings** — live web (lowest priority, freshness only)

## Filtering Rules

Skip any finding that:
- Has summary < 20 characters
- Starts with `%PDF` (raw binary)
- Contains "smoke test" or "this file exists to verify"
- Is clearly a generic web result unrelated to the user's request

## Output Format

When generating slides.json, each slide's content fields must:
- `headline`: Specific, factual, drawn from evidence (not generic marketing copy)
- `body`: 2-3 sentences using actual findings with specific details
- `bullets`: Each bullet is a complete, evidence-backed sentence
- `items`: Each data point has a `source` field citing the finding ID
