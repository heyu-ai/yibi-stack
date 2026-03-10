# Debug Issue

Structured debugging methodology for this project. Enforces root cause analysis before suggesting fixes.

## Phase 1: Triage — Understand the Error

Before touching any code:

1. Ask for (or parse from context): the **exact error message**, **affected module/function**, **stack trace**, and **when it started**.
2. Identify the error category:
   - **Runtime error** → Python exception, missing dependency, config issue
   - **Browser automation** → Playwright timeout, selector change, page structure change
   - **Data parsing** → CSV format change, unexpected input, encoding issue
   - **Environment** → missing `.env` vars, auth token expired

## Phase 2: Config & Environment Check

```bash
# Check .env files
ls -la .env*

# Check recent changes that may have caused regression
git log --oneline -10
git diff HEAD~5
```

**Common issues in this project:**
- `.env` missing required variables
- Playwright browser not installed (`playwright install`)
- Target website structure changed

## Phase 3: Apply Fix

Only after identifying root cause:
1. Apply the **minimal** fix.
2. If it's a config issue: update all relevant locations.
3. If it's a website change: update selectors/parsing logic.

## Phase 4: Verify — User-Facing Behavior (CRITICAL)

**Do NOT declare success based on error disappearance alone.**

```bash
# Run full test suite
uv run pytest

# Test the specific functionality that was broken
uv run python -m skills.<affected_module>
```

Only report success after confirming the original problem is resolved.

## Phase 5: Prevent Recurrence

After fixing, note:
- What was the root cause?
- What check would have caught this earlier?
- Should a test be added to prevent regression?
