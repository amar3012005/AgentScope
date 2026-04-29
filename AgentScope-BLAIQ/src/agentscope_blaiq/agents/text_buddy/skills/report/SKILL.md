---
name: report
description: Rules for composing professional reports.
---
# TextBuddy — Report Artifact Skill

## Artifact Type
Structured text report — a long-form, evidence-grounded document for decision-makers,
stakeholders, or technical audiences. Covers analysis, findings, recommendations, and
supporting data. Delivered as well-structured prose with clear sections and inline citations.

## Template Structure

Generate the report with these sections in order:

### 1. Executive Summary
- Open with 3-5 sentences summarising the entire report.
- State the scope, key finding, and primary recommendation.
- Write for readers who may only read this section — make it self-contained.
- Cite the top 2-3 supporting sources inline.

### 2. Background / Context
- Explain what prompted this report and what it covers.
- Include relevant timeframe, scope boundaries, and data sources used.
- Reference any prior reports, decisions, or initiatives if mentioned in HITL answers.
- Keep to 1-2 paragraphs.

### 3. Key Findings
- Present 4-8 numbered findings in order of importance.
- Each finding:
  - **Finding**: One clear, specific statement — no vague generalisations.
  - **Evidence**: 1-3 inline citations `[source:ID]` supporting the claim.
  - **Confidence**: High / Medium / Low based on source recency and reliability.
- Flag any contradictory evidence in a sub-bullet rather than suppressing it.
- Separate factual findings from inferences — mark inferences with "Analysis suggests."

### 4. Analysis
- Synthesise findings into a coherent narrative (3-6 paragraphs).
- Connect findings: what patterns emerge? What do they mean collectively?
- Quantify impact where evidence supports it: revenue, risk, opportunity, timeline.
- Distinguish between what the evidence proves vs. what it suggests.
- If critical evidence is missing, name the gap explicitly.
- Cite sources throughout — do not defer citations to a bibliography.

### 5. Recommendations
- Provide 3-6 numbered, actionable recommendations.
- Each recommendation:
  - **Action**: Specific, concrete — who should do what.
  - **Rationale**: Which findings and sources support this (`[source:ID]`).
  - **Priority**: Critical / High / Medium / Low.
  - **Timeline**: Specific timeframe or trigger condition.
- Order by priority, highest first.
- If evidence is insufficient to strongly support a recommendation, flag it as provisional.

### 6. Conclusion
- Restate the report's core message in 2-3 sentences.
- Confirm the primary call to action.
- Note any outstanding questions that require further investigation.

### 7. Appendix (optional)
- Include only if HITL answers or evidence pack references supplementary data.
- Do not pad with restated findings — appendix is for source details or methodology.

## Formatting Rules

- Use clear H2/H3 section headings throughout.
- Bold key numbers, names, and conclusions within body text.
- Use numbered lists for findings and recommendations (not bullets — ordered sets need order).
- Use bullet points for sub-items within findings.
- Tables are required when comparing 3+ data points across 2+ dimensions.
- Aim for 600-1500 words depending on the scope indicated in HITL answers.
  - "Short report" → 600-800 words.
  - "Standard report" → 800-1100 words.
  - "Detailed/comprehensive" → 1100-1500 words.

## Citation Rules

- Every factual claim must carry an inline `[source:ID]` citation.
- Group multiple sources supporting one claim: `[source:MEM-3, source:WEB-7]`.
- HITL answers are treated as first-party input — cite as `[source:HITL]`.
- Place citations immediately after the claim, not at the end of the paragraph.
- If a section has no citable evidence, write: "No supporting evidence available for this section."

## Tone Rules

- Analytical and neutral — present facts and evidence, not editorial opinions.
- Match formality to audience: board/executive = formal and concise;
  technical = precise with terminology; operational = direct and action-focused.
- Use HITL answers to calibrate audience and formality — if user specified "investors",
  lean toward strategic framing; if "technical team", lean toward specifics.
- Avoid filler phrases: no "it is worth noting," no "needless to say," no "importantly."
- State uncertainty explicitly — weak evidence warrants hedged language; strong evidence does not.
- Write in third person unless HITL specifies otherwise.

## Rules

- Never invent statistics, names, dates, or company details not present in evidence.
- If the evidence pack is sparse, write a shorter report rather than speculating.
- Contradictory evidence must appear in the findings — do not suppress inconvenient data.
- If HITL answers include a specific title for the report, use it verbatim as the H1.
- The report must be self-contained — a new reader should not need the evidence pack
  to understand the conclusions.
