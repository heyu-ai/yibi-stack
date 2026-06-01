---
id: "0002"
title: "CC Bash Parser Bug Workaround — PreToolUse Hook for D3/D4/D5 Patterns"
status: accepted
date: 2026-06-02
deciders: [howie]
related:
  upstream_issue:
    repo: anthropics/claude-code
    number: 56018
    title: "Unhandled node type: string — bash parser rejects valid grep BRE / nested subshell / jq single-quote patterns"
    posted: 2026-05-04
    cc_version: "2.1.118"
  pr: TBD
---

## Context

Claude Code's built-in bash command parser reports `Unhandled node type: string` for three
syntactically valid bash patterns (tracked as anthropics/claude-code#56018):

| ID | Pattern | Example |
|----|---------|---------|
| D3 | `grep "pat1\|pat2"` — double-quoted BRE alternation | `grep "foo\|bar" file.txt` |
| D4 | `$(outer "$(inner)")` — reverse-nested subshell | `dirname "$(git rev-parse --git-dir)"` |
| D5 | `$(jq 'filter')` — single-quoted jq filter in subshell | `$(jq -r '.key' config.json)` |

When the parser encounters these patterns, it raises an error that halts the bash tool call
entirely — the command never executes. The patterns are correct bash; the bug is in the tool-layer
parser, not in the commands themselves.

### Why Not Just Avoid the Patterns?

All three patterns appear naturally in agent-generated bash:
- D3: BRE alternation is a standard grep idiom for multi-term search
- D4: Nested subshell for path computation is the idiomatic alternative to `cd &&`
- D5: jq single-quoted filter is the canonical form in every jq tutorial

Asking the agent to remember three arbitrary parser bugs per session was unreliable in practice.

## Decision

Intercept all three patterns with a PreToolUse hook (`bash-ap1-inline-check.sh`) before
Claude Code's parser sees the command. The hook:

1. Prints a fix suggestion with priority ordering (Grep tool > ERE > BRE single-quote)
2. Exits with code 2 (block), preventing the parser error
3. Records a JSONL audit event to `.runtime/logs/bash-hygiene-audit.jsonl`

The hook runs in the detection path before the bash parser, so the parser error never surfaces.

### Fix Suggestion Priority (D3)

The D3 fix suggestion is ordered to align with project best practice
(`rules-context.md` § Prefer Built-in Tools Over Bash for Code Search):

1. **A) Claude Code built-in Grep tool** — zero CWD dependency, no hook trigger, no manual truncation
2. **B) `grep -Ei 'pat1|pat2'`** — ERE flag, GNU-recommended for portability (per GNU grep manual)
3. **C) `grep -i 'pat1\|pat2'`** — BRE single-quote, valid but backslash-prone

D6 (`rg-bre-misuse`) already uses Grep tool as option A; D3 now follows the same ordering.

## Consequences

**Positive:**
- Parser errors no longer disrupt agent workflow for D3/D4/D5 patterns
- Fix suggestions guide the agent toward best practice rather than just unblocking
- Audit log provides visibility into how often each pattern is intercepted

**Negative / Trade-offs:**
- Maintenance cost: each new CC parser-bug pattern requires a new Python regex in the hook
- False negatives: regex-based detection cannot cover all quoting variants (deeply nested,
  heredoc-wrapped, or dynamically assembled commands may slip through)
- Runtime cost: Python subprocess invoked on every Bash tool call (~3ms overhead, negligible)

**Rejected alternatives:**
- *Train the agent to avoid the patterns* — unreliable; the patterns are idiomatic and agents
  forget per-session rules under context pressure
- *Patch CC directly* — anthropics/claude-code#56018 posted 2026-05-04; not yet fixed;
  patching is not viable for end users

## Removal Condition

**When CC fixes #56018**, remove D3/D4/D5 detections from the hook. Steps:

1. Verify: open a new Claude Code session and confirm `grep "foo\|bar" file.txt` executes
   without `Unhandled node type: string`
2. Remove the three detection blocks from both:
   - `plugins/bash-hygiene/hooks/bash-ap1-inline-check.sh`
   - `.claude/hooks/bash-ap1-inline-check.sh`
3. Keep D1/D2/D6 — those intercept anti-patterns in the agent's logic, not CC parser bugs
4. Update this ADR status to `superseded`

Regression monitoring: see `.claude/hooks/tests/test_cc_parser_bug_regression.py` —
the test asserts the GitHub issue is still open; it will fail when the issue closes,
prompting manual verification and removal.

## Status History

| Date | Status | Note |
|------|--------|------|
| 2026-06-02 | accepted | Initial implementation |

**Last verified (CC parser still buggy):** 2026-06-02 (CC 2.1.118, issue #56018 open)
