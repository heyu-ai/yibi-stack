---
name: investigate
version: 1.0.0
description: Systematic debugging with root cause investigation. Investigate to root cause, then fix, then hand off to the PR flow (/pr-cycle-fast, /pr-review-cycle).
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Grep
  - Glob
  - AskUserQuestion
  - WebSearch
triggers:
  - debug this
  - fix this bug
  - why is this broken
  - root cause analysis
  - investigate this error
---
<!--
  Adapted from the `investigate` skill in garrytan/gstack (MIT, Copyright (c) 2026
  Garry Tan) — see LICENSE.gstack in this directory. The debugging methodology
  (Iron Law, five phases, pattern table, scope lock, sanitize-before-search) is
  kept and re-homed; gstack-product plumbing (telemetry, config toggles, gbrain
  context queries, session/artifacts machinery, branded voice) is dropped. Prior-
  learnings recall is re-pointed at this repo's /lessons system (~/.agents/bin/
  lessons, yibi-stack #267 Part B), replacing gstack's gbrain/~/.gstack store.
-->

## When to invoke this skill

Five phases: investigate, analyze, hypothesize, implement, verify. Iron Law: no
fixes without root cause. Use when asked to "debug this", "fix this bug", "why is
this broken", "investigate this error", or "root cause analysis". Invoke this
skill (do NOT debug directly) when the user reports errors, 500s, stack traces,
unexpected behavior, "it was working yesterday", or is troubleshooting why
something stopped working.

Investigation is the front of a flow: once the fix is confirmed and verified,
hand off to the PR lifecycle (`/pr-cycle-fast` for small changes,
`/pr-review-cycle` or `/pr-cycle-deep` for larger ones).

## Interaction gates (read once)

Several phases below have mandatory question gates. If the host's AskUserQuestion
mechanism is unavailable or fails, NEVER silently pick an option: fall back to
asking in plain prose, or report `BLOCKED` with what you needed. A missing answer
is not a licence to guess.

## Iron Law

**NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST.**

Fixing symptoms creates whack-a-mole debugging. Every fix that does not address
the root cause makes the next bug harder to find. Find the root cause, then fix it.

## Phase 1: Root Cause Investigation

Gather context before forming any hypothesis.

1. **Collect symptoms:** Read the error messages, stack traces, and reproduction
   steps. If the user has not provided enough context, ask ONE question at a time
   via AskUserQuestion.

2. **Read the code:** Trace the code path from the symptom back to potential
   causes. Use Grep to find all references, Read to understand the logic.

3. **Check recent changes:**
   ```bash
   git log --oneline -20 -- <affected-files>
   ```
   Was this working before? What changed? A regression means the root cause is in
   the diff.

4. **Reproduce:** Can you trigger the bug deterministically? If not, gather more
   evidence before proceeding.

5. **Check history:** Look for prior fixes in the same area (`git log`, the
   project's issue/TODO source if present). Recurring bugs in the same files are
   an architectural smell, not a coincidence.

6. **Recall prior learnings.** Search the lessons store for patterns and pitfalls
   recorded against the area you are debugging, so a bug already solved once
   surfaces before you re-derive it. `lessons search` matches on a SINGLE keyword
   — a multi-word phrase returns nothing — so pick one noun: the failing component
   or the affected file's basename without extension (`auth`, `celery`,
   `onboarding`), alphanumeric or hyphen only.
   ```bash
   LESSONS="$HOME/.agents/bin/lessons"
   if [ -x "$LESSONS" ]; then
     "$LESSONS" search "<affected-area-keyword>" --last 10 --include-legacy 2>/dev/null || true
   else
     echo "prior-learnings recall skipped: $LESSONS not found"
   fi
   ```
   This is an area-keyed first pass; you re-search with the specific hypothesis
   noun below once you have one. If a returned lesson applies, say which one in one
   sentence ("Prior learning applied: <key>"). If nothing comes back, that absence
   is itself useful — no prior fix recorded for this area.

**Stop before a dangerous assumption.** For high-stakes ambiguity — architecture,
data model, destructive scope, or genuinely missing context — STOP now, before
forming the hypothesis. Name the ambiguity in one sentence, present 2-3 options
with tradeoffs, and ask. The 3-strike rule in Phase 3 only catches you after
three failed hypotheses; it does not protect against one confident wrong
assumption made here. The user has context you do not: domain knowledge, timing,
relationships, taste.

Output: **"Root cause hypothesis: ..."** — a specific, testable claim about what
is wrong and why.

**Refresh learnings for the hypothesis.** The pull above was keyed to debugging
broadly. Now re-search keyed to *this* hypothesis so prior fixes for the same
problem-shape surface. Pick ONE keyword: a noun — the failing component, the file
basename without extension, or the bug noun. It MUST be alphanumeric or hyphen
only (no quotes, slashes, dots, colons, whitespace); simplify to the alphanumeric
stem if needed. Good: `auth-cookie`, `session-expiry`, `redirect-loop`. Bad:
`auth.ts:47`, `fix the auth bug`.

```bash
LESSONS="$HOME/.agents/bin/lessons"
[ -x "$LESSONS" ] && "$LESSONS" search "<your-keyword>" --last 5 --include-legacy 2>/dev/null || true
```

Name which returned lesson applies in one sentence, or note that none did.

## Scope Lock

After forming your root cause hypothesis, lock edits to the affected module to
prevent scope creep. This repo ships a `freeze` skill (harness plugin) whose
PreToolUse hook blocks any Edit/Write outside a chosen boundary directory.

Identify the narrowest directory containing the affected files and invoke
`/freeze` on it (e.g. `freeze edits to backend/src/auth/`). Tell the user:
"Edits restricted to `<dir>/` for this debug session; run `/unfreeze` to remove
the restriction." If the bug genuinely spans the whole repo or the scope is
unclear, skip the lock and say why.

## Phase 2: Pattern Analysis

Check if this bug matches a known pattern:

| Pattern | Signature | Where to look |
|---------|-----------|---------------|
| Race condition | Intermittent, timing-dependent | Concurrent access to shared state |
| Nil/null propagation | NoMethodError, TypeError | Missing guards on optional values |
| State corruption | Inconsistent data, partial updates | Transactions, callbacks, hooks |
| Integration failure | Timeout, unexpected response | External API calls, service boundaries |
| Configuration drift | Works locally, fails in staging/prod | Env vars, feature flags, DB state |
| Stale cache | Shows old data, fixes on cache clear | Redis, CDN, browser cache |

**External pattern search:** If the bug does not match a pattern above, WebSearch
for "{framework} {generic error type}" or "{library} {component} known issues".
**Sanitize first:** strip hostnames, IPs, file paths, SQL, and customer data.
Search the error *category*, not the raw message. If WebSearch is unavailable,
skip and proceed to hypothesis testing.

## Phase 3: Hypothesis Testing

Before writing ANY fix, verify your hypothesis.

1. **Confirm the hypothesis:** Add a temporary log statement, assertion, or debug
   output at the suspected root cause. Run the reproduction. Does the evidence
   match?

2. **If the hypothesis is wrong:** Optionally search for the error first —
   **sanitize again** (strip hostnames, IPs, paths, SQL fragments, customer
   identifiers, and any internal/proprietary data; if the message is too specific
   to sanitize safely, skip the search). This second sanitize is deliberate: retry
   pressure is exactly when a raw error message leaks. Then return to Phase 1,
   gather more evidence, and do not guess.

3. **Stop if you are looping.** If you are circling the same diagnostic, the same
   file, or the same failed-fix variants, STOP and reassess — escalate or gather
   fresh evidence. Unproductive loops may never produce three explicit
   hypotheses, so the 3-strike rule below will not catch them.

4. **3-strike rule:** If 3 hypotheses fail, **STOP**. Use AskUserQuestion:
   ```
   3 hypotheses tested, none match. This may be an architectural issue
   rather than a simple bug.

   A) Continue investigating — I have a new hypothesis: [describe]
   B) Escalate for human review — this needs someone who knows the system
   C) Add logging and wait — instrument the area and catch it next time
   ```

**Red flags** — if you see any of these, slow down:
- "Quick fix for now" — there is no "for now." Fix it right or escalate.
- Proposing a fix before tracing data flow — you are guessing.
- Each fix reveals a new problem elsewhere — wrong layer, not wrong code.

## Phase 4: Implementation

Once root cause is confirmed:

1. **Fix the root cause, not the symptom.** The smallest change that eliminates
   the actual problem.

2. **Minimal diff:** Fewest files touched, fewest lines changed. Resist the urge
   to refactor adjacent code. Genuinely unrelated rewrites are separate scope,
   never a rider on a bug fix.

3. **Write a regression test** that **fails** without the fix (proves the test is
   meaningful) and **passes** with it. Cover the edge cases and error paths the
   root cause implicates, not only the happy path — a single test passing does not
   prove the class of bug is closed.

4. **Run the full test suite.** Paste the output. No regressions allowed.

5. **If the fix touches >5 files:** Use AskUserQuestion to flag the blast radius:
   ```
   This fix touches N files. That's a large blast radius for a bug fix.
   A) Proceed — the root cause genuinely spans these files
   B) Split — fix the critical path now, defer the rest
   C) Rethink — maybe there's a more targeted approach
   ```

## Phase 5: Verification & Report

**Fresh verification:** Reproduce the original bug scenario and confirm it is
fixed. This is not optional. Run the test suite and paste the output.

Report evidence concretely: name the files, functions, line numbers, commands,
and actual output. "auth.ts:47 returned undefined when the session cookie
expired; added a null check + redirect, test at auth_test.ts:88 fails without it"
beats "I fixed the authentication issue."

Output a structured debug report:
```
DEBUG REPORT
========================================
Symptom:         [what the user observed]
Root cause:      [what was actually wrong]
Fix:             [what was changed, with file:line references]
Evidence:        [test output, reproduction attempt showing fix works]
Regression test: [file:line of the new test]
Related:         [issue/TODO items, prior bugs in same area, architectural notes]
Status:          DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
========================================
```

**Escalate** — do not push through — after 3 failed hypotheses, for any
uncertain security-sensitive change, or for scope you cannot verify. When
escalating or blocked, report `STATUS`, `REASON`, `ATTEMPTED`, `RECOMMENDATION`.

Once the report is DONE and verified, hand off to the PR flow
(`/pr-cycle-fast`, `/pr-review-cycle`, or `/pr-cycle-deep`).

## Capture the lesson

If you discovered a non-obvious pattern, pitfall, or architectural insight, record
it so a future session can find it. In this repo that is the `/lessons` system:

```bash
~/.agents/bin/lessons add --type <pattern|pitfall|architecture|tool|operational> \
  --key <short-key> --insight "<what you learned>" --confidence <1-10> \
  --source observed --files <affected/file>
```

Only log genuine discoveries — something that would save time in a future
session. Do not log obvious facts or one-off transient errors. Phase 1 recalls
these at the start of the next investigation, so what you capture here is what
surfaces there — the loop that makes the store compound over time.

## Important Rules

- **3 failed hypotheses (not fix attempts) → STOP and question the architecture.**
  Under the Iron Law you should not have applied a fix yet; it is failed
  *diagnostic approaches* that trigger the stop. Wrong architecture, not wrong
  hypothesis.
- **Detect loops early.** Circling the same file/diagnostic without three distinct
  hypotheses still means STOP.
- **Never apply a fix you cannot verify.** If you cannot reproduce and confirm,
  do not ship it.
- **Never say "this should fix it."** Verify and prove it. Run the tests.
- **If a fix touches >5 files → AskUserQuestion** about blast radius first.
- **High-stakes ambiguity or security-sensitive uncertainty → STOP and ask/escalate.**
- **Completion status:**
  - `DONE` — root cause found, fix applied, regression test written, all tests pass.
  - `DONE_WITH_CONCERNS` — verified locally, but a specific external/staging-only
    condition remains unverified (name it). If you cannot verify the fix at all,
    that is `BLOCKED`, not this.
  - `BLOCKED` — root cause unclear after investigation, or the fix cannot be
    verified; escalated.
  - `NEEDS_CONTEXT` — missing information; state exactly what is needed.
