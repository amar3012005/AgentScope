---
name: codebase-validator
description: Use when validating code changes, commit summaries, contract layers, workflow changes, or test claims after a code edit. This skill verifies diffs against the repository state, checks affected tests and boundaries, and separates confirmed facts from inferred claims.
---

# Codebase Validator

Use this skill when you need to verify that a change is real, safe, and accurately described.

## Core rule

Never trust a summary alone. Verify against:
- git state
- changed files
- direct source inspection
- relevant tests
- contract/runtime boundaries

## Workflow

1. Identify the claim being validated.
2. Read the actual diff or commit.
3. List the files changed and classify them:
   - contract layer
   - runtime / orchestration
   - tests
   - docs
   - unrelated dirty state
4. Use the code-review graph first when the repo has it.
   - get minimal context
   - detect changed functions/classes
   - identify impacted flows
   - identify test gaps
5. Verify the concrete claims in the smallest possible scope.
   - counts
   - exports
   - schema names
   - compatibility checks
   - workflow/template definitions
   - test results
6. If the claim mentions “zero runtime changes”, confirm the working tree and commit scope.
7. Distinguish:
   - verified
   - partially verified
   - not verified
   - contradicted
8. Report residual risk clearly.

## Repo-specific checklist

For BLAIQ contract/workflow changes, also read:
- [validation checklist](references/blaq-validation-checklist.md)

Use that checklist when the change touches:
- contracts
- dispatch validation
- workflow templates
- registry exports
- agent/tool compatibility
- test counts or commit summaries

## Validation checks

### Structural checks
- Are the files present?
- Are the symbols exported?
- Are the new types wired into the registry?
- Are the contracts isolated from runtime imports if that is the intent?

### Behavioral checks
- Do tests exist for the new layer?
- Do targeted tests pass?
- Do the new contracts reference real runtime names?
- Are tool and agent references bidirectionally consistent?

### Change-scope checks
- Does the commit only touch the claimed layer?
- Are there unrelated modified files in the worktree?
- Are dirty files outside the commit relevant to the claim?

## Output format

When reporting validation:
- start with the verdict
- list verified claims first
- list mismatches next
- include file paths for every claim
- do not blur “likely” with “confirmed”

## For workflow/contract migrations

Prefer this order:
1. contracts
2. validation helpers
3. registry
4. tests
5. docs
6. runtime binding

If the change claims to stop before runtime binding, confirm that runtime files were not modified in the commit itself.
