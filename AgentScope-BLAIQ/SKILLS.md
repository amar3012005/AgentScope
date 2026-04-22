# Development Skills & Task Framework

**Project**: AgentScope-BLAIQ  
**Updated**: 2026-04-22  
**Mode**: Modular, atomic tasks with clear boundaries

---

## Pre-Task Template

Use this for every new task. Fill before work starts.

```
## TASK: [Name]

### Goal
[One sentence outcome]

### Context
- What exists: [files/systems affected]
- What's broken: [current state]
- What depends: [downstream modules]
- Tech stack: [langs, libs, versions]

### Constraints
- No rewrites of: [list files/modules to preserve]
- Must integrate with: [existing systems]
- Cannot change: [API contracts, schemas]
- Environment: [local/prod, versions]

### Module Breakdown
- [ ] Module A: [responsibility] → output: [file/test]
- [ ] Module B: [responsibility] → output: [file/test]
- [ ] Integration: [how modules talk] → output: [passing test]

### Input/Output Contracts
**Inputs:**
- Type: [data shape, origin]
- Format: [JSON/dict/etc]
- Validation: [checks needed]

**Outputs:**
- Type: [data shape]
- Location: [file/endpoint/log]
- Format: [JSON/dict/etc]

### Success Criteria
- [ ] Code passes syntax check
- [ ] Unit tests passing (80%+ coverage)
- [ ] Integration test passing
- [ ] No breaking changes to existing APIs
- [ ] Logging in place for production debug
- [ ] Journal updated

### Known Risks
- Risk 1: [description] → mitigation: [fix]
- Risk 2: [description] → mitigation: [fix]

### Session Commands
**Build**: [exact command to run]
**Test**: [exact command to verify]
**Lock**: [file move or commit]
```

---

## Quick Reference: Build Cycle

```
1. PARSE TASK (fill template above)
2. READ EXISTING (graph search + key files)
3. PLAN MODULES (1 per session max)
4. CODE (test-first)
5. VERIFY (run tests, check logs)
6. JOURNAL (append result)
7. NEXT TASK (repeat)
```

---

## Integration Checkpoints

After **every 2–3 modules**, run:

```bash
# Mock upstream/downstream
# Call new code with real data shapes
# Verify: no type mismatches, no cascade breaks
```

---

## Error Handling (Surgical Fixes)

If code breaks:
1. Paste error + context (10 lines)
2. Ask: "Fix line X: [error]. What assumption?"
3. No rewrites. One surgical fix.
4. Test immediately in same session.

---

## Journal Format

```
| Date | Task | Module | Status | Notes |
|------|------|--------|--------|-------|
| 2026-04-22 | TASK-NAME | ModuleA | ✅ DONE | Added logging, 2 tests passing |
```

---

## Ready

Give me task. I'll fill template, build modular, test surgical, no waste.
