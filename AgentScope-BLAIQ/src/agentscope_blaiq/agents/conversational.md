# Conversational Mode — Strategic Planner Routing Prompt

## Purpose

This prompt guides the strategic planner's LLM-based route classifier to detect
conversational messages that do NOT need the research → HITL → synthesis pipeline.

## Three-Way Route Classification

The strategic planner classifies every user message into one of three tiers:

### 1. `conversational` — No research needed

Greetings, chitchat, thanks, meta-questions about the system.
The engine responds directly with a short friendly message.
No research agent, no HITL depth question, no artifact pipeline.

**Signals:**
- Greeting words: hello, hi, hey, good morning, thanks, bye
- Meta-questions: "what can you do?", "who are you?", "how does this work?"
- Very short messages (1-3 words) without topic-specific keywords
- Emotional expressions: "cool", "nice", "awesome", "great"
- Language-agnostic greetings: hola, hallo, bonjour, guten tag, moin

**NOT conversational** (these need research):
- "hello, what products does Solvis have?" → direct_answer (has a knowledge question)
- "thanks, now create a pitch deck" → artifact (has a creation request)

### 2. `direct_answer` — Research + synthesize, no artifact

Knowledge questions that need evidence lookup but no artifact creation.
The engine runs research → auto-selects depth → synthesizes answer.
HITL depth question is skipped — depth auto-selected by source count.

**Signals:**
- Question words: what, who, where, when, how, why, which
- Knowledge verbs: tell me, explain, describe, summarize, list, compare
- Topic-specific queries: product names, technical terms, company names
- "what do we know about X", "give me info on Y"

### 3. `artifact` — Full pipeline

Explicit creation requests that need research + content planning + rendering.
Full workflow: strategist → research → HITL → content_director → vangogh → governance.

**Signals:**
- Creation verbs: create, make, build, generate, design, render
- Writing verbs: write, compose, draft, send, prepare
- Artifact types mentioned: pitch deck, poster, report, email, memo, proposal, invoice
- "make me a...", "write an email to...", "design a poster about..."

## LLM Classification Prompt

The strategic planner sends this to the routing model (fast, low-token):

```
User request: "{query}"

Classify this request into ONE of three categories:

- conversational: greetings, chitchat, thanks, meta-questions about the system,
  or anything that does NOT need research or evidence lookup.
- direct_answer: asking for facts, details, specs, explanation, summary.
  Requires looking up information from memory or the web.
- artifact: explicitly asks to PRODUCE a deliverable (pitch deck, email, report, etc.)

Return ONLY JSON: {"route": "conversational" or "direct_answer" or "artifact", "confidence": 0.0-1.0}
```

## Heuristic Fallback

If the LLM call fails, the strategist falls back to keyword heuristics:

1. Check `_is_conversational_heuristic()` — short greetings, ≤2 words without topic keywords
2. Check `is_direct_knowledge_query()` — question patterns, knowledge verbs
3. Default to `artifact` if neither matches

## Engine Behavior Per Route

| Route | Research | HITL | Artifact | Response time |
|-------|----------|------|----------|--------------|
| conversational | Skip | Skip | Skip | ~1-2s (single LLM call) |
| direct_answer | Yes (quick recall) | Skip (auto-depth) | Skip | ~5-10s |
| artifact | Yes (full) | Yes (requirements) | Yes (full pipeline) | ~30-60s |

## Auto-Depth Selection (direct_answer)

When HITL depth question is skipped, depth auto-selects:
- ≤3 sources → "Brief executive answer" (800 tokens)
- >3 sources → "Detailed product summary" (6000 tokens)

Users can still get the HITL depth question by submitting through the artifact workflow.
