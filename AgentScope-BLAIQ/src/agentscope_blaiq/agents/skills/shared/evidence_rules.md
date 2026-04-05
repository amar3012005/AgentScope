# Evidence Rules — Mandatory for ALL Artifact Generation

## CRITICAL: Anti-Hallucination Policy

1. **ONLY use content from the provided evidence findings.** Do NOT generate facts, statistics, names, or claims from your training data.
2. If a section has insufficient evidence, write: "Insufficient evidence for this section" — do NOT fill with generic content.
3. Every sentence with a factual claim MUST map to a specific finding from the evidence pack.
4. If the user's HITL answers provide direction, use those as the primary guide. Evidence supplements HITL answers.
5. When web findings and memory findings conflict, prefer memory findings (enterprise ground truth).

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
