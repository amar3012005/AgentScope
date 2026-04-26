# BLAIQ Validation Checklist

Use this when verifying a change summary after code edits.

## 1. Confirm change scope

- `git status --short`
- `git show --stat --summary --oneline HEAD`
- `git show --name-only --format=oneline HEAD`

Check whether the commit actually touched the files claimed in the summary.
Call out unrelated dirty files separately.

## 2. Verify contract claims

For contract-layer changes:
- check the declared types exist
- check exports are present in `contracts/__init__.py`
- check registry helpers load the intended symbols
- check validation functions exist and are called by tests

## 3. Verify workflow claims

For workflow-template changes:
- confirm the template registry exists
- confirm each template is a DAG
- confirm each node references real agents
- confirm each required tool exists
- confirm approval gates and fallback branches are explicit

## 4. Verify runtime isolation

If the summary says "zero runtime changes":
- inspect the commit file list, not just the journal
- check whether files under `agents/`, `app/`, or `workflows/engine.py` changed
- distinguish commit scope from dirty working tree scope

## 5. Verify test claims

Run the tests that cover the changed layer:
- `tests/test_harnesses.py`
- `tests/test_dispatch.py`
- `tests/test_workflows.py`
- `tests/test_contracts.py`
- `tests/test_strategic_catalog.py`

Prefer the bundled Python runtime for consistency.
If dependencies are missing, install only what is required to execute the tests.

## 6. Report truthfully

Split results into:
- verified
- partially verified
- not verified
- contradicted

If the summary says "all files committed", verify the actual git commit contents.
If the summary says "N/N tests passing", verify with an executed test run, not the journal entry.
