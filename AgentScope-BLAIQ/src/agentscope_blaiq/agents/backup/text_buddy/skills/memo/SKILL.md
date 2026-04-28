---
name: memo
description: Rules for composing internal memos.
---
# TextBuddy — Internal Memo Artifact Skill

## Artifact Type
Internal memo — a concise internal communication document for organizational decision-making.

## Template Structure

Generate the memo with these sections in order:

### 1. Memo Header Block
- **TO**: Recipient name(s) and title(s), or team/department name.
- **FROM**: Sender name and title.
- **DATE**: Full date format ("April 10, 2026").
- **SUBJECT**: Clear, specific subject line under 80 characters.
  Write "Q3 Budget Reallocation: Engineering +15%, Marketing -10%"
  not "Budget Update."

Format each field on its own line, bold the labels, separate from the body
with a horizontal rule.

### 2. Executive Summary
- Lead with the decision, recommendation, or key finding in 2-3 sentences.
- Assume the reader may stop here — this section must stand alone.
- State the "so what" upfront: what changed, what is needed, or what was decided.
- If a decision requires approval, state that explicitly.

### 3. Background / Context
- Provide 1-2 paragraphs of relevant context.
- Answer: Why is this memo being written now? What prompted this?
- Reference prior decisions, meetings, or events with specific dates.
- Cite evidence findings with `[source:ID]` for factual claims.

### 4. Analysis / Details
- Present the detailed reasoning, data, or findings in 2-4 paragraphs.
- Use subheadings if covering multiple distinct topics.
- Include bullet points for comparisons, options, or lists of factors.
- Support every analytical claim with evidence — no unsupported assertions.
- If presenting options, structure as:
  - **Option A**: Description, pros, cons, cost/effort
  - **Option B**: Description, pros, cons, cost/effort
  - **Recommended**: Which option and why

### 5. Action Items
- List each action item as a bullet point with this structure:
  - **[Owner Name]**: Action description — **Deadline: [date]**
- Be specific about who does what by when.
- Number the action items if sequence matters.
- Limit to 3-7 action items — if more are needed, group by workstream.

### 6. Next Steps / Timeline
- State the next milestone, meeting, or checkpoint.
- Include a specific date or timeframe: "Review progress at the April 25 team standup."
- If approval is needed, state the approval process and deadline.

## Length and Formatting Rules

- Target 1-2 pages (300-600 words for the body, excluding header).
- Use bullet points aggressively — memos are scanned, not read word by word.
- Bold key terms, names, numbers, and deadlines for scannability.
- One idea per paragraph. Keep paragraphs to 3-4 sentences maximum.
- Use subheadings to break content into scannable chunks.

## Tone Rules

- Direct and decisive — memos drive action, not discussion.
- Write in first person plural ("We recommend...") for team-authored memos,
  first person singular ("I recommend...") for individual-authored.
- Avoid hedging language: write "We should" not "We might want to consider."
- Professional but not stiff — contractions are acceptable in internal memos.
- Assume the reader is busy — respect their time with concise phrasing.

## Rules

- Lead with the recommendation — never bury the conclusion at the end.
- Every action item must have an owner and a deadline. Unassigned items are useless.
- If the memo presents a decision already made, state it as fact, not as a suggestion.
- If the memo requests a decision, clearly state who decides and by when.
- Never include sensitive HR, legal, or compensation details unless HITL explicitly provides them.
- If HITL answers specify the audience (exec team, full department, etc.), adjust depth accordingly.
