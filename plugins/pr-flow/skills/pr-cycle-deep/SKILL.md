---
name: pr-cycle-deep
type: know
scope: global
description: >
  Mob review by multiple frontier-model agents — 完整 PR 生命週期含跨家 LLM
  group review：自動偵測 codex / agy，≥1 家即啟動
  R1 獨立 + conditional R2 交叉 debate + aggregate；Review Contract 與 Evidence gate
  決定 blocking set，fix → bounded re-review → 人類快速複查 → CI → merge → archive。
  適用中大型 PR / 高風險改動 / 跨家視角壓力測試 / SDD 專案。小型 PR 或快速 lifecycle
  請改用 `/pr-cycle-fast`（Claude-only state machine）。純 PR review 不需完整 lifecycle
  請改用 `/pr-review-cycle`（4 個 pr-review-toolkit subagent 平行）。只想 review 別人的 PR、給建議但不改 code / 不 merge 請改用 `/mob-code-review-only`。
  偵測不到任何外部模型時提示使用者退回 `/pr-review-cycle`。
  觸發情境：「mob review」「group review」「multi-model PR review」「跨家 LLM review」
  「pr-cycle-deep」「frontier model 群審」「找 codex + agy 一起 review」「deep review」
---

# PR Cycle — Deep (Multi-Agent Mob Review)

Complete workflow for multi-frontier-model mob review of a PR, applicable to any tech stack (Python / JS / Go / Flutter / others).

**When to use mob mode**:

- Medium/large PR (>200 lines diff, or crosses multiple modules)
- High-risk changes (auth, payment, migration, infra, security-sensitive)
- Want to stress-test whether multiple LLM families consistently flag the same issues
- Willing to spend 10–30 minutes for broader coverage

**When to use `/pr-cycle-fast` or `/pr-review-cycle`**:

- Small feature / bug fix / refactor: use `/pr-cycle-fast` (full lifecycle) or `/pr-review-cycle` (review only)
- Codex not installed and agy (Antigravity CLI) not installed: use `/pr-review-cycle`

**Core philosophy**: when codex / agy are detected, they review alongside Claude as **synchronous
parallel** reviewers — independent, then cross-reading to debate into an aggregated report. Claude
(lead) fixes per the report and re-reviews within the bounded loop (Step 7); the human then scans in
a few minutes and the lead responds on the spot — faster than two senior engineers, broader in view.

## Usage

```text
/pr-cycle-deep
/pr-cycle-deep #<PR number>   ← skip PR creation, but still run the Step 1 Review Contract gate
```

---

## Step 0 — Reviewer Detection (determine workflow mode)

### Step 0a — Read detection cache & auto-verify auth

Use the Read tool to try reading `~/.claude/mob-detection-cache`:

- **File exists** (warm path): **do not ask whether to use the cache** — the default is silent
  reuse. Trust the cached binary detection + mode, but **re-verify the auth tokens** for the
  cached-available voices (auth can go stale even when the binary is unchanged). Run only the auth
  detection checks from Step 0b for each voice the cache marks available (`CODEX_OK=1` /
  `GEMINI_OK=1`):
  - the `CODEX_AUTH:` bash block (Codex)
  - the `GEMINI_AUTH:` bash block (agy)

  Then branch on the result:
  - **All cached-available voices still auth OK** → report one line and **go directly to Step 1**:

    ```text
    [Cache] Reusing detection ({{DATE}}): Mode={{MODE}} — auth re-verified OK, proceeding.
    ```

  - **Any cached-available voice now `NOT_AUTHED` / `KEY_WHITESPACE_PREFIX`** → that token expired
    or broke. Do **not** proceed and do **not** silently drop the voice. Show the fix command for
    that voice (see the Step 0b report block / Troubleshooting), wait for the user to
    re-authenticate, then re-run Step 0 from **0b** (full re-detect + refresh cache).
- **File does not exist** (Read tool returns error): run Step 0b directly.

> **Why re-verify instead of asking**: valid auth is the common case, so silent reuse is the
> default; only a real auth failure stops the flow. A present-but-expired token that slips the
> static check is caught at use-time by R1 fail-loud (`agy_validate.py` / codex error), which marks
> that voice unavailable and proceeds with the rest — no block. The warm path re-verifies auth only,
> not `GEMINI_ALLOW_LIST` (a stale allow-list only adds a per-call prompt). Force a full re-detect
> by deleting `~/.claude/mob-detection-cache`.

### Step 0b — Run detection

Four bash calls for quick detection (binary detection and auth detection separated; auth uses if/elif/else to ensure mutually exclusive output):

```bash
# Codex CLI binary
which codex >/dev/null 2>&1 && echo "CODEX: BINARY_OK" || echo "CODEX: NOT_FOUND"
```

```bash
# Codex auth (KEY_SET or FILE_EXISTS either satisfies)
if env | grep -qE '^(CODEX_API_KEY|OPENAI_API_KEY)=[^[:space:]]'; then
  echo "CODEX_AUTH: KEY_SET"
elif env | grep -qE '^(CODEX_API_KEY|OPENAI_API_KEY)=[[:space:]]'; then
  echo "CODEX_AUTH: KEY_WHITESPACE_PREFIX"
elif test -s ~/.codex/auth.json; then
  echo "CODEX_AUTH: FILE_EXISTS"
else
  echo "CODEX_AUTH: NOT_AUTHED"
fi
```

```bash
# Antigravity CLI (agy) binary (output keeps GEMINI: prefix for mob-detection-cache GEMINI_OK key compatibility)
which agy >/dev/null 2>&1 && echo "GEMINI: BINARY_OK" || echo "GEMINI: NOT_FOUND"
```

```bash
# Antigravity CLI (agy) auth (onboardingComplete is the reliable indicator that OAuth completed)
if python3 -c 'import json,pathlib,sys; p=pathlib.Path.home()/".gemini"/"antigravity-cli"/"cache"/"onboarding.json"; sys.exit(0 if p.is_file() and json.loads(p.read_text()).get("onboardingComplete") else 1)'; then
  echo "GEMINI_AUTH: ONBOARDED"
elif env | grep -qE '^(GEMINI_API_KEY|GOOGLE_API_KEY)=[^[:space:]]'; then
  echo "GEMINI_AUTH: KEY_SET"
elif env | grep -qE '^(GEMINI_API_KEY|GOOGLE_API_KEY)=[[:space:]]'; then
  echo "GEMINI_AUTH: KEY_WHITESPACE_PREFIX"
else
  echo "GEMINI_AUTH: NOT_AUTHED"
fi
```

```bash
# Confirm Claude Code allow list (agy calls without confirmation dialog)
python3 -c 'import json,pathlib,sys; p=pathlib.Path.home()/".claude"/"settings.json"; d=json.loads(p.read_text()) if p.is_file() else {}; allow=d.get("permissions",{}).get("allow",[]); sys.exit(0 if "Bash(agy:*)" in allow else 1)' && echo "GEMINI_ALLOW_LIST: OK" || echo "GEMINI_ALLOW_LIST: MISSING"
```

### Mode determination

An external reviewer is "available" = binary OK + auth OK (Codex or Gemini).

**Gemini (agy) auth OK states**: `KEY_SET` and `ONBOARDED` both count as auth OK (`ONBOARDED` means `onboardingComplete: true`, i.e. OAuth completed).

**`BINARY_OK + NOT_AUTHED` handling**: a binary found but with failed auth (`NOT_AUTHED` /
`KEY_WHITESPACE_PREFIX`) is **not** "available". Do not enter the count table below and do not
silently count it as one fewer voice (the user would then assume it is uninstalled, not broken):
**stop**, show the fix command, and re-run Step 0 after they confirm.

| Available external reviewers | Action |
| ---: | --- |
| 0 (all NOT_FOUND, no auth failures) | **Fall back to `/pr-review-cycle`** (Claude-only is sufficient; this skill terminates) |
| **1** (Codex or Gemini) | **2-voice mob** (Claude + 1 external; cross-model debate is already meaningful) |
| **2** (Codex + Gemini) | **3-voice full mob** (broadest coverage) |

Report detection results to the user and wait for confirmation before continuing:

```text
Detection results:
- Claude  ✓ (pr-review-toolkit; if that plugin is not installed → /code-review fallback)
- Codex   ✓ / ✗ / ✗ (auth failed; run codex login then re-run Step 0)
- Gemini (agy) ✓ / ✗ / ✗ (auth failed: ONBOARDED or KEY_SET either works;
                run agy to complete browser OAuth (onboardingComplete → true), or set GEMINI_API_KEY env var)
- Allow list: OK / MISSING (MISSING does not block execution, but every agy call will prompt for confirmation;
              fix: run make patch-agy-allow-list or make install-all)

External reviewer count: {{N}}/2
Mode: {{2-voice-mob | 3-voice-full-mob | REDIRECT}}

  ← If REDIRECT: this skill terminates; run /pr-review-cycle instead
  ← If auth failure: fix auth first, then re-run detection from this step
Proceed to Step 1?
```

After detection completes (not REDIRECT, no auth failures), write the result to `~/.claude/mob-detection-cache` using the Write tool (for Step 0a reuse next time):

```text
DATE={{today YYYY-MM-DD}}
CODEX_OK={{1 (available) or 0 (unavailable)}}
GEMINI_OK={{1 (available) or 0 (unavailable)}}
MODE={{3-voice-full-mob | 2-voice-mob}}
```

---

## Review Severity Standard (RFC 2119)

> **Owner**: `/pr-review-cycle` SKILL.md "Review Severity Standard (RFC 2119)" defines the
> canonical grading. This is a condensed summary for in-context use — when the standard changes,
> re-summarise from the owner; do **not** copy-paste.

Every finding (Claude / Codex / Gemini voice) is graded with an
[RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) strength keyword, by *merge consequence*:

| RFC 2119 | Grade | Merge consequence |
|----------|-------|-------------------|
| **MUST** | Critical | Blocks merge |
| **SHOULD** | Important | Defer only with a documented reason in the PR |
| **MAY** | Actionable NIT | Does not block merge — fix opportunistically (see Step 5) |

MUST = functional / security / PII-in-logs / data-loss / explicit-baseline violation.
SHOULD = test gaps on changed critical paths, silent failures, naming / structure
inconsistency, misleading docs. MAY = concrete, actionable small fixes: naming, comment typo, import order, small documentation clarification.
Subjective preference with no verifiable reason is **not a finding** — discard it.

---

## Workflow (mob review mode)

### Step 1 — Create PR + Review Contract gate

If no PR exists yet, run in order:

```bash
git branch --show-current
```

```bash
git status --short
```

Confirm you're on a feature branch, then commit + push + create PR:

```bash
git add <files>
```

```bash
git commit -m "..."
```

> 多行 message：用 Write tool 寫到 `$CLAUDE_JOB_DIR/commit_msg.txt`，再 `git commit -F`。
> 不要用 `"$(cat <<'EOF')"` —— 外層 `"..."` 包 `$()` 觸發 Quoting Rule 2；heredoc 讓命令跨多行，allow-list 無法 match。

```bash
git push -u origin HEAD
```

Before creating or reviewing the PR, its body MUST contain this exact PR-specific contract:

```text
## Review Contract
### Goal
<the single user or operator outcome this PR must deliver>
### Non-goals
<explicit scope exclusions; cannot waive repo security/data-integrity baselines>
### Accepted Residual Risks
- Failure mode / impact: ...; Accepted boundary: ...; Mitigation: ...;
  Detection / recovery: ...; Accepted by: <human name or handle>
### Acceptance Criteria
- AC-1: <concrete testable condition required for LGTM>
### Follow-ups
- <explicitly deferred hardening; non-blocking unless promoted by human amendment>
```

For a new PR, the lead drafts this contract from the matching spec/change and writes the complete PR
body to `$CLAUDE_JOB_DIR/pr-body.md` with the Write tool, then creates the PR:

```bash
gh pr create --title "..." --body-file "$CLAUDE_JOB_DIR/pr-body.md"
```

For an existing PR, read `title,body`; if any heading is missing or Acceptance Criteria is empty,
draft a complete body preserving unrelated content, show every missing field, and update it with
`gh pr edit "{{pr_number}}" --body-file "$CLAUDE_JOB_DIR/pr-body.md"`. **Do not launch R1 while the
contract is incomplete.** Show the final section to the user and wait for explicit confirmation.
The confirmed text is the **frozen Review Contract** for this review pass.

A **material amendment** changes Goal, Non-goals, Accepted Residual Risks, Acceptance Criteria, or
adds in-scope behavior: update the PR body, record why, obtain human confirmation, then restart
full-diff R1. An **editorial amendment** (spelling, formatting, links, no semantic change) keeps the
current pass. Until a material amendment is confirmed, use the frozen snapshot and stop reviewing
the proposed new scope.

Use `/commit-commands:commit-push-pr` only when it preserves the confirmed contract in the PR body.

Note the PR number as `{{pr_number}}` and the base branch as `{{base_branch}}` (usually `main`). At
Step 3.1, paste the confirmed contract into `$REVIEW_DIR/review-contract.md` and `prompt-r1.md`.

---

### Step 1.5 — Parallel Pre-review Check (3 agents, same message)

This step is **blocking** — do not proceed to Step 2 if any agent fails or returns no usable output.

Spawn three Task agents **in a single message** to gather baseline information in parallel:

| Agent | Task |
|-------|------|
| **diff-reviewer** | Run `gh pr diff {{pr_number}}`; summarise changed files and line counts. **Do not use local `main`** — always fetch from GitHub. If the command exits non-zero, report `[FAIL] gh pr diff: <exact error>` and stop. |
| **ci-checker** | Run `gh pr checks {{pr_number}}`; report pass / fail / pending per check. If the list is empty, report "CI: not yet triggered". If the command exits non-zero, report `[FAIL] gh pr checks: <exact error>` and stop. |
| **amplifier-verifier** | Run TC coverage + docstring traceability check: `python3 ~/.agents/skills/pr-cycle-deep/scripts/amplifier-verify.py --pr {{pr_number}}`. Exit 0 = no spectra change or all TCs traced; exit 1 = MUST or SHOULD findings present; exit 2 = fatal error (missing testplan, parse failure, gh error). Report the full stdout. On exit 2, stop with `[FAIL]`. On exit 1, **do not stop** — write MUST findings to `$REVIEW_DIR/final.md` Critical section and SHOULD findings to Important section, then continue to Step 2. |

If any agent reports `[FAIL]` (exit 2 or explicit `[FAIL]` in output), stop and report the failure explicitly; do not proceed to Step 2.

Once all three return successfully, write `$CLAUDE_JOB_DIR/pre-review-check.md` (distinct from `$REVIEW_DIR/final.md` used in later steps) and report inline:

```text
Pre-review Check
- Diff: <file count> files, <line count> lines changed
- CI: <pass / fail / pending / not yet triggered — list any failing checks by name>
- Amplifier: <MUST: N findings / SHOULD: N findings / OK: all TCs traced / no spectra change>
```

---

### Step 2 — Code Review (defect detection)

Run `/code-review` to scan all PR changes for correctness bugs (`/code-review high` for stricter
effort; add `--comment` to post findings as GitHub PR inline comments):

```text
/code-review
```

- **No findings** → proceed to Step 3.
- **Has findings** → bring into Step 6 (Fix) with the mob results. `/code-review` **does not modify code**; findings are review comments, no separate commit needed.

> **Fallback (Claude Code < 2.1.146)**: if `/code-review` reports `Unknown skill: code-review`,
> use `pr-review-toolkit:code-reviewer` agent instead (same behavior — report only, no code changes):
>
> ```text
> Agent(subagent_type=pr-review-toolkit:code-reviewer,
>       prompt="Code review all diffs in this PR; report bugs / convention violations / logic errors")
> ```

---

### Step 3 — Round 1: Independent parallel review

**Goal**: each voice (Claude / Codex / Gemini) reviews independently **without seeing each
other's findings**, to avoid anchoring bias. Each voice writes its findings to `<voice>-r1.md`
in the review dir (referred to below as `$REVIEW_DIR`).

#### 3.1 — Prepare working directory and shared prompt

Write all R1/R2 intermediate files to the review dir (`<worktree-root>/.pr-review/`, `$REVIEW_DIR`).
The worktree-root namespace isolates concurrent sessions, overwrites old output on re-run, and keeps
files off `/tmp/` (the sandbox rejects it). The agy scripts **inline** this content into
`agy -p "$CONTENT"` rather than `@file` (issue #153: `@file` fails in nested worktrees and triggers
agentic mode); `--add-dir "$WT_ROOT"` still lets agy look up surrounding code.

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/setup-review-dir.sh {{base_branch}}
```

The script's last line outputs `REVIEW_DIR=<absolute path>` as informational; subsequent bash
calls do not need to parse this output — derive directly from the worktree root
(`WT_ROOT=$(git rev-parse --show-toplevel); REVIEW_DIR="$WT_ROOT/.pr-review"`, equivalent).

The script owns safe base resolution: `set -euo pipefail`, fresh `git fetch`, `FETCH_HEAD`, and
`upstream` when present (else `origin`). Do not replace it with a local-ref diff; that reopens stale
base and fork-base failures (issues #22/#196). `Bash()` allow-list rules do not expand `~`, so use
the expanded absolute path:

```text
Bash(bash /Users/<you>/.agents/skills/pr-cycle-deep/scripts/setup-review-dir.sh *)
Bash(bash /Users/<you>/.agents/skills/pr-cycle-deep/scripts/codex-r1-stage1.sh)
```

`setup-review-dir.sh` needs `*` for its branch argument; `codex-r1-stage1.sh` is exact. The extract
prompt is fixed at `~/.agents/skills/pr-cycle-deep/prompts/extract-r1.md` (`make install` symlink).

Write the review prompt to `$REVIEW_DIR/prompt-r1.md` using the Write tool (`$REVIEW_DIR` is
the actual path derived above, e.g. `/path/to/worktree/.pr-review`). Replace `{{REVIEW_DIR}}`
with the actual `$REVIEW_DIR` value before writing:

```text
You are a senior code reviewer. Review the following PR diff independently.

Output ONLY the review in the format below. Do not narrate your actions or write any
preamble (no "I will...", "Let me...", "I'm going to...", "I have written..."), and do
not announce file reads. Your first line must be the "## Summary" heading.

Base branch: {{base_branch}}
PR #: {{pr_number}}
Diff: see {{REVIEW_DIR}}/diff.patch
Changed files: see {{REVIEW_DIR}}/changed-files.txt

## Frozen Review Contract
<paste the exact human-confirmed ## Review Contract section from the PR body>

Output format (strictly follow, for downstream aggregation):

## Summary
<1-2 sentence overall assessment>

## Findings

### [Critical] <short title>
- File: <path:line>
- Issue: <description>
- Contract mapping: <AC-ID | repo baseline: path/rule | unaccepted risk: description>
- Evidence: <the evidence lead can use to reproduce this defect; form depends on finding type — see Evidence forms below>
- Suggested fix: <how to fix>

### [Important] <short title>
- File: <path:line>
- Issue: <description>
- Contract mapping: <AC-ID | repo baseline: path/rule | unaccepted risk: description>
- Evidence: <the evidence lead can use to reproduce this defect; form depends on finding type — see Evidence forms below>
- Suggested fix: <how to fix>

### [Actionable NIT] <short title>
- Must be a concrete, actionable small fix (naming, comment error, import order, etc.), not subjective preference

## Verdict
- LGTM / NEEDS_CHANGES

Severity (RFC 2119 — grade by merge consequence, not by how bad it feels):
- [Critical] = MUST fix, blocks merge: logic / functional error, security hole, secret or PII in logs, data loss, explicit baseline violation
- [Important] = SHOULD fix (defer only with a documented reason): test gap on a changed critical path, silent failure / swallowed exception, naming / structure inconsistency, misleading doc or comment
- [Actionable NIT] = MAY fix: a concrete, actionable small fix (naming, comment typo, import order) — never a subjective preference

Focus on:
- Logic errors, race conditions, security holes, silent failures, resource leaks
- Test coverage gaps (critical paths not tested)
- Documentation / comment inconsistency with implementation
- A Critical / Important item can block only when Contract mapping uses one of the three listed
  sources. Do not invent an Acceptance Criterion or expand Goal scope.
- Work wholly inside Non-goals, an accepted risk boundary, or Follow-ups is non-blocking unless it
  violates a located repo security/data-integrity baseline. Accepted risks require `Accepted by:`.
- Do NOT list "code style preferences" or "subjective aesthetics" — non-actionable items only
- Be skeptical, be terse, no compliments

Evidence forms (closed enumeration — the `Evidence:` field on a [Critical] / [Important] finding
MUST match your finding's type below; a type not in this list carries no blocking evidence and is
deferred, not merged against). You review a diff, not a checkout — so no runnable command is ever
required:

| Finding type | Required `Evidence:` form |
| --- | --- |
| Logic / functional error, security hole | A concrete failure scenario: the input or state that triggers it and the wrong output / crash that results. |
| Test coverage gap | The production line left unverified plus a mutation that would survive the current tests (what you could break with the tests still green). |
| Doc / comment factual error | The single command output or diff line that proves the statement wrong. |
| Naming / structural inconsistency | A grep result showing at least 2 sibling occurrences of the convention this diff departs from. |
| Precision / subjective quality ("unclear", "not precise enough") | No acceptable evidence form exists — always deferred, never a merge gate. |
```

#### 3.2 — Launch 3 voices in parallel

**In the same message**, send all reviewer calls in parallel (only send available voices):

##### Claude voice (pr-review-toolkit 4 subagents)

Launch four Task subagents in parallel (each produces independent findings; the lead merges them into the Claude voice):

> **If the `pr-review-toolkit` subagents are not available** (the external `pr-review-toolkit`
> plugin is not installed in this project): `[WARN]` the Claude voice falls back to the built-in
> `/code-review` skill (report-only) for this round; prompt the user to install for the full
> 4-subagent Claude voice:
> `claude plugin marketplace add anthropics/claude-plugins-official && claude plugin install pr-review-toolkit@claude-plugins-official`

| Subagent | Focus |
| --- | --- |
| `code-reviewer` | Convention compliance, bugs, logic errors |
| `silent-failure-hunter` | Silent failures, swallowed exceptions |
| `pr-test-analyzer` | Test coverage gaps |
| `comment-analyzer` | Documentation / comment accuracy |

After all four complete, the lead uses the Write tool to merge them into `$REVIEW_DIR/claude-r1.md` (following the output format above).

##### Codex voice (when CODEX_OK)

###### Stage 1: Guarded review via `codex exec` (raw output lands on disk, does not enter main context)

> **Execution note**: `codex review --base` rejects a positional prompt (codex-cli 0.142.5:
> `the argument '[PROMPT]' cannot be used with '--base <BRANCH>'`), so a skill-hijack guard
> cannot ride on it (issue #194). The script instead feeds guard + `prompt-r1.md` + the shared
> `diff.patch` to `codex exec` via stdin (same channel as `codex-r2.sh`). The review lands on
> **stdout** → `codex-r1-raw.md`; stderr → `codex-r1.stage1.log`. **Run directly — do not append
> `> $CLAUDE_JOB_DIR/foo.log 2>&1`** (see rule 16 **(2) Bash redirect `>`**) — on failure, Read
> `$REVIEW_DIR/codex-r1.stage1.log` for the full error.

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/codex-r1-stage1.sh
```

The script takes no base-branch argument — it reviews the shared `$REVIEW_DIR/diff.patch` that
Step 3.1 already produced, so all three voices review the identical diff. Raw output lands in
`codex-r1-raw.md` — **do not read it in the main context**.

The script pins `-m gpt-5.6-sol` (codex-cli >= 0.144) instead of local config. If the stage log says
the model needs a newer Codex, run `codex update`; confirm frontier slugs in `models_cache.json`.

###### Stage 2: Extract (compress verbose raw markdown into structured JSON)

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/codex-r1-stage2.sh
```

###### Stage 3: Render (lead reads JSON → writes compact markdown)

Lead reads `$REVIEW_DIR/codex-r1.json` with the Read tool and branches on the result:

**JSON valid** (valid JSON with `verdict` / `summary` / `findings` fields) → use the Write tool to render `$REVIEW_DIR/codex-r1.md` (compact markdown, sorted by severity: critical → important → actionable_nit).

**JSON invalid** (not valid JSON or missing fields) → do not render; fall back: Read
`$REVIEW_DIR/codex-r1-raw.md`, manually summarize in the main context, Write compact markdown to
`$REVIEW_DIR/codex-r1.md`, then note in final.md "Codex voice used raw form this round; main context load is higher".

##### Gemini voice (when GEMINI_OK)

agy does not accept a combined stdin prompt + diff path; concatenate into a single file first:

###### Stage 1: Native review (raw output lands on disk, does not enter main context)

> **Execution/security contract**: run the script verbatim; never append `$?` logic or redirects.
> It inlines prompt+diff (never `@file`, issue #153), clears stale scratch input, and validates
> timeout/agentic/wrong-target output with `agy_validate.py`. Stage 1 retains
> `--dangerously-skip-permissions` for surrounding-code lookup, so use only on trusted repos: the
> review-only guard forbids edits and before/after `git status` emits `[WARN]` on mutation, but the
> lead must audit and undo any unintended change. Stage 2 stays sandboxed. On failure, read
> `$REVIEW_DIR/gemini-r1.stage1.log`; never trust a voice claiming it implemented a fix.

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/agy-r1-stage1.sh
```

The script pins `--model 'Gemini 3.1 Pro (Low)'`. Do not remove the flag: `agy`'s auto-select
resolves to Gemini 3.5 Flash, and its model list also contains Claude Sonnet/Opus — an
auto-selected Claude would silently collapse this voice into the same family as the Claude lead,
defeating the cross-family premise with no warning. The tier was `(High)` originally, but it
failed consistently on this machine; `(Low)` produces reviews reliably and is still a Gemini Pro
tier, so the cross-family premise holds (AGYS-DT-008 asserts only the `Gemini` prefix, so the
High↔Low swap does not affect the test). `agy models` lists the valid display names;
an invalid value fails loud and prints the list. Raw output lands in `gemini-r1-raw.md` —
**do not read it in the main context**.

###### Stage 2: Extract (agy auto-selects lightweight model to extract JSON)

> **Execution note**: the script writes stderr to `$REVIEW_DIR/gemini-r1.extract.log`; stdout only
> outputs "agy R1 Stage 2 complete". **Run directly — do not append `> $CLAUDE_JOB_DIR/foo.log 2>&1`**
> (harness auto-capture is redundant here; see rule 16 **(2) Bash redirect `>`** for `Bash(verb:*)` allow-list patterns) —
> on failure, Read `$REVIEW_DIR/gemini-r1.extract.log` for the full error.

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/agy-r1-stage2.sh
```

Note: `agy` automatically selects a lightweight model in the extract stage to avoid consuming more high-reasoning quota.

###### Stage 3: Render (same as Codex voice: lead reads JSON → writes compact markdown)

Lead reads `$REVIEW_DIR/gemini-r1.json` with the Read tool and branches:

**JSON valid** → use the Write tool to render `$REVIEW_DIR/gemini-r1.md` (same format as Codex compact markdown).

**JSON invalid** → read `$REVIEW_DIR/gemini-r1-raw.md` with the Read tool, manually summarize
in main context, write compact markdown with the Write tool; note in final.md:
"Gemini voice used raw form this round".

#### 3.3 — Sanity check

```bash
WT_ROOT=$(git rev-parse --show-toplevel)
REVIEW_DIR="$WT_ROOT/.pr-review"
ls -lh "$REVIEW_DIR/codex-r1.md" "$REVIEW_DIR/codex-r1.json" 2>&1
ls -lh "$REVIEW_DIR/gemini-r1.md" "$REVIEW_DIR/gemini-r1.json" 2>&1
```

Check:

1. `codex-r1.md` / `gemini-r1.md` (compact markdown) < 50 bytes or missing → Stage 3 render not completed; re-run
2. `codex-r1.json` / `gemini-r1.json` is invalid JSON → extract failed; trigger fallback (see FAQ)
3. `*-r1-raw.md` < 200 bytes or contains only error message → re-run Stage 1 (native review)

2 consecutive failures → mark that voice as "unavailable for this PR"; record in the final aggregated report; do not block the workflow.

`r1-aggregate.md` only references compact versions (`*-r1.md`); **never reference raw versions (`*-r1-raw.md`)**.

---

#### 3.4 — R2 activation gate

After all R1 voices return, the lead performs a zero-execution preliminary gate on every
Critical/Important item. A **candidate blocker** has both (1) a valid `Contract mapping:` source and
(2) a structurally valid `Evidence:` form. A **blocking dispute** exists when voices disagree about
the same item's mapping, blocking severity, or disposition. NIT, missing mapping, and malformed or
absent evidence never activate R2.

- Candidate blocking set empty **and** no blocking dispute → report
  `R2 skipped: no contract-blocking candidate or dispute`, skip Step 4, and aggregate R1 in Step 5.
- At least one candidate blocker **or** blocking dispute → run Step 4 for all active voices.

This gate applies on the initial review and every bounded re-review pass.

---

### Step 4 — Round 2: Cross-debate (conditional)

Enter this step only when Step 3.4 activates it. Each voice reads the other voices' R1 findings and
takes positions (agree / disagree / supplement), forcing out consensus and disputes.

#### 4.1 — Generate R1 aggregate

Use the Write tool to concatenate all R1 content into `$REVIEW_DIR/r1-aggregate.md` (only voices
that produced output; replace `$REVIEW_DIR` with the actual path and paste each voice's compact markdown in full):

```text
# Round 1 Findings — Independent Results per Reviewer

## Claude
<paste $REVIEW_DIR/claude-r1.md content>

## Codex (if CODEX_OK)
<paste $REVIEW_DIR/codex-r1.md content>

## Gemini (if GEMINI_OK)
<paste $REVIEW_DIR/gemini-r1.md content>
```

#### 4.2 — Round 2 prompt

Write `$REVIEW_DIR/prompt-r2.md` with the Write tool:

```text
You just reviewed this PR in Round 1. Now read the other reviewers' results
and take positions:

Output ONLY the response in the format below. Do not narrate your actions or write any
preamble (no "I will...", "Let me...", "I'm going to...", "I have written..."), and do
not announce file reads. Your first line must be the "## Cross-review verdict" heading.

## Round 1 Results from All Reviewers
<r1-aggregate content>

## Your task
For each finding raised by other reviewers:
- AGREE: agreed, reason (optional)
- DISAGREE: disagree, reason (required)
- DUPLICATE: duplicates your R1 finding X
- UPGRADE/DOWNGRADE: severity should be adjusted to ___, reason

Additional:
- After reading others' reviews, what did you miss in R1? Add new [Critical/Important/NIT] items.
- Which R1 items do you want to withdraw after seeing others' opinions? Mark WITHDRAW + reason.

Output format:

## Cross-review verdict
<2-3 sentences: your view on the other reviewers' overall performance>

## Per-finding response
### Other reviewer's finding: <original finding title>
- Verdict: AGREE/DISAGREE/DUPLICATE/UPGRADE/DOWNGRADE
- Reason: ...

## New findings (missed in R1)
### [Critical/Important/NIT] <title>
- File / Issue / Fix

## Withdrawals (R1 items I'm retracting)
- <original title>: reason

## Final verdict
- LGTM / NEEDS_CHANGES
```

#### 4.3 — Send R2 to each voice in parallel

Each voice uses the same call pattern, but this time the prompt is R2 and the input is r1-aggregate (not the raw diff):

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/codex-r2.sh
```

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/agy-r2.sh
```

> **Security note**: `agy-r2.sh` uses `--dangerously-skip-permissions` (for `--add-dir`, same as Stage 1)
> and inlines the prompt (issue #153); it assumes a trusted repo — for external-fork PRs, evaluate prompt-injection risk first.

Only send to available voices (CODEX_OK / GEMINI_OK).

Claude voice: the lead writes `$REVIEW_DIR/claude-r2.md` after reading r1-aggregate — no subagents needed (avoid 4×4 = 16 reviews generating too much noise).

---

### Step 5 — Aggregator synthesis

After reading all R1 plus any activated R2, produce `$REVIEW_DIR/final.md`, graded per the
[Review Severity Standard](#review-severity-standard-rfc-2119) (Critical = MUST, Important = SHOULD,
Actionable NIT = MAY). Blocking is decided by the Evidence gate below; NIT never blocks any round.

| Grade | Condition | Action |
| --- | --- | --- |
| **Consensus Critical** | ≥2 voices mark Critical with no DISAGREE | Must fix |
| **Consensus Important** | ≥2 voices mark Important with no DISAGREE | Must fix |
| **Disputed** | 1 voice marks Critical/Important; others DISAGREE | List the dispute; user decides |
| **Single-voice Critical** | 1 voice marks Critical; others did not mention | Lead **empirically refutes or confirms** (run a minimal repro), not judge-by-reasoning → confirmed: elevate to Consensus; refuted: drop with the evidence noted; can't test: list as Disputed |
| **Actionable NIT** | Any 1 voice marks NIT and it's not subjective preference | **Deferred — never blocks**, any round. Lead MAY fix trivially in-round; doing so is not a gate |
| **Withdrawn** | Marked WITHDRAW in R2 | Remove from list |
| **Voice unavailable** | That voice failed R1/R2 twice in a row | Note in final.md; do not block |

#### Contract mapping gate

A Critical / Important finding is eligible for the Evidence gate only when `Contract mapping:` is
one of: `AC-<id>`, `repo baseline: <path/rule>`, or `unaccepted risk: <description>`. Missing or
invalid mapping is moved to deferred with its original text and reason preserved. Work wholly inside
Non-goals, Follow-ups, or a documented accepted boundary is non-blocking. An accepted risk needs all
five fields from Step 1, including `Accepted by:`; a voice or lead cannot accept it for the human.
Repo security/data-integrity baselines cannot be waived by any Review Contract section.

#### Evidence gate

A Critical / Important finding blocks merge **only** if it carries a valid `Evidence:` in the form
its type requires (see Evidence forms in the R1 prompt). The gate is applied at aggregation, before
any fixing, and is **tiered by cost** so most rejections execute nothing:

| Tier | Applies to | Action |
| --- | --- | --- |
| Structure check | any finding | `Evidence:` missing or not the required form → **demote immediately, executing nothing** |
| Verify | Critical with well-formed evidence | lead **must** reproduce it (run the minimal repro / confirm the failure scenario) |
| Spot-check | Important with well-formed evidence | lead **may** verify selectively; unverified Important stays blocking in Round 1 only |

A demoted finding is **moved, never dropped**: it goes to `## Deferred for lack of evidence` with
its original title, description, and demotion reason **preserved verbatim** — the lead must not
silently discard it.

Verifying well-formed evidence has three outcomes — do not collapse "invalid" into "absent":

| Outcome | Disposition |
| --- | --- |
| Reproduced | stays blocking |
| Not reproduced | moved to deferred, recorded as "evidence did not reproduce" |
| Invalid (evidence itself is broken / won't run) | lead fixes it once; if still unusable, **demote to Important into deferred — never drop, never record it as "not reproduced"** |

Disposition by severity × evidence × round (every cell defined — no gaps, no ambiguity):

| Severity | Evidence | Round 1 | Round 2 |
| --- | --- | --- | --- |
| Critical | valid | blocking | blocking |
| Critical | none | deferred | deferred |
| Important | valid | blocking | **deferred** (R2 blocks on Critical only) |
| Important | none | deferred | deferred |
| Actionable NIT | valid | non-blocking | non-blocking |
| Actionable NIT | none | non-blocking | non-blocking |

> **Single-voice [P0]/[Critical] → verify with a repro before acting — and re-verify before *citing* a past
> verdict** (esp. CLI flag-parsing / runtime claims, which often reason from a plausible-but-wrong model).
> **Record the tool version**: a stored verdict expires when the tool changes. Example (PR #157 → #229): agy's
> `[P0] --print eats --add-dir` was once refuted by `printf 'reply ALPHA' | agy --print` → `ALPHA`; on **agy 1.1.2**
> that no longer holds and the finding is now correct. The `@file` caution stands: inline via `-p "$CONTENT"`, never `@file`.

`final.md` format:

```text
# Final Aggregated Review — PR #{{pr_number}}

## Mode
group-review ({{N}}/3 voices active)

## Contract compliance
- Acceptance Criteria verified: <AC-ID → evidence>
- Scope drift: none / <unapproved change>
- Residual risks: fixed / accepted by <human> within <boundary>

## Consensus Critical (must fix)
1. <finding>...

## Consensus Important (must fix)
1. <finding>...

## Actionable NIT (deferred — never blocks; fix opportunistically)
1. <finding>...

## Deferred for lack of evidence (not blocking; reason stated per item)
1. <finding> — demoted: <reason>...

## Outside contract (not blocking; mapping reason stated per item)
1. <finding> — <Non-goal / accepted boundary / Follow-up / invalid mapping>...

## Disputed (user decides)
- Voice X argues Critical: <reason>
- Voice Y disagrees: <reason>
- Lead recommendation: <decision guidance>

## Voices unavailable
- <voice>: <reason>
```

Report the final.md summary to the user and wait for Disputed item decisions before proceeding to Step 5b.

---

### Step 5b — Post review summary to PR

Post the aggregated consensus as a PR comment **before** fixes start, so the decision trail is
recorded for later readers. Recompute `REVIEW_DIR` in the same block as `gh pr comment` (each Bash
call is a fresh shell, else `--body-file` expands empty); skip without blocking if `final.md` is missing:

```bash
WT_ROOT=$(git rev-parse --show-toplevel)
REVIEW_DIR="$WT_ROOT/.pr-review"
if [ ! -f "$REVIEW_DIR/final.md" ]; then
  echo "[WARN] final.md missing -- skip posting; complete Step 5 first, then continue to Step 6"
else
  gh pr comment "{{pr_number}}" --body-file "$REVIEW_DIR/final.md"
fi
```

- **exit 0** → report the comment URL.
- **non-zero** (auth / network / PR not found) → `[WARN] 無法貼 review summary 到 PR`; show the user the manual command, then **continue to Step 6** (posting must not block fixes).

First-time use may prompt for permission → add `Bash(gh pr comment:*)` to `settings.local.json`
(rule 16 safe form). MVP posts one comment here; re-post after Step 7 only if consensus materially changed.

---

### Step 5c — 降級 Important 批次 issue

降級的 Important（`final.md` 的 `## Deferred for lack of evidence` 段落中 severity 為 Important 者）
需要有人承接，去處是**每個 PR 至多一張** GitHub issue，標 `deferred-from-review`，一次列出該 PR
全部降級 Important。降級的 Actionable NIT **不開票**——它留在 Step 5b 已貼的 PR comment 裡。沒有降級
Important 時**不建立** issue。

時機：Round 2 結束後建立一次。circuit breaker（人類裁決）路徑下**同樣建立**——降級 Important 與未解
blocking 是兩回事，前者不因後者而消失。

執行前先確認 label 存在。若 `gh label list --repo {{owner/repo}}` 找不到 `deferred-from-review`：
`[FAIL] deferred-from-review label 不存在 — 請先執行 gh label create deferred-from-review，再繼續。`

label 就位且有降級 Important 時，把它們彙整成單一 issue body（逐項保留原標題／描述／降級理由），建立一張：

```bash
gh issue create --repo {{owner/repo}} --label deferred-from-review --title "Deferred from review: PR #{{pr_number}}" --body-file "$REVIEW_DIR/deferred-issue.md"
```

`gh issue create` 非零退出（auth／label 不存在／網路）→ `[WARN]` 回報，不阻斷流程。

---

### Step 6 — Fix (Critical → Important → NIT)

Process in order:

1. Modify the code.
2. Run local CI (read the project to find the CI command first):

   ```bash
   grep -E "^(ci|test|check):" Makefile 2>/dev/null | head -5
   ```

   Common mappings:

   | Stack | Local CI |
   | --- | --- |
   | Python (make) | `make ci` |
   | Python (bare) | `uv run pytest` |
   | Node | `npm test` |
   | Go | `go test ./...` |
   | Flutter | `flutter test` |

   Fix before continuing if CI fails — do not skip.

3. Commit (describe what was fixed; do not write "fix review comments"):

   ```bash
   git commit -m "fix(...): ..."
   ```

   ```bash
   git push
   ```

Commit after each batch of fixes to make it easier for group re-review to see the corresponding diff.

**Recheck PR status before looping back into re-review.** A group re-review (Step 7) is
expensive — do not spend it on a PR that is no longer open or mergeable. After pushing, re-query
the live PR state:

```bash
gh pr view "{{pr_number}}" --json state,mergeable,mergeStateStatus -q '.state + " / " + .mergeable + " / " + .mergeStateStatus'
```

Route by the result. The decision table is authoritative — do not proceed on a row that says STOP:

| `state` | `mergeStateStatus` / `mergeable` | Meaning | Action |
| --- | --- | --- | --- |
| `MERGED` | any | Someone merged the PR out-of-band | **STOP the cycle** — skip re-review; go straight to Step 9 (archive / retro). Do not push more. |
| `CLOSED` | any | PR closed without merging | **STOP** — surface to the user and wait; do not continue. |
| `OPEN` | `DIRTY` / `mergeable=CONFLICTING` | Fixes (or a base advance) created merge conflicts | Resolve conflicts against `{{base_branch}}`, commit, push, then re-run this recheck before Step 7. |
| `OPEN` | `BEHIND` | Base branch advanced since this branch forked | Update the branch from `{{base_branch}}` (merge or rebase per repo convention) and push, so Step 7 R1/R2 review against the current base — otherwise findings are computed against a stale base. |
| `OPEN` | `CLEAN` / `BLOCKED` / `UNSTABLE` / `HAS_HOOKS` / `UNKNOWN` | Open and not conflicting (may still await CI/approvals) | Continue to Step 7. |

If `gh pr view` itself errors (auth / network), stop and report — an empty result is not "OPEN".

---

### Step 7 — Group re-review (bounded to two rounds)

The re-review loop is **bounded**: Round 1, then at most Round 2, then it exits — to a merge or to
human adjudication. There is no "run one more round to see."

| Round | Review surface | Can block merge | On exit |
| --- | --- | --- | --- |
| Round 1 | the **full diff**; record the baseline head SHA (`git rev-parse HEAD`) before Step 6 fixes — the next round's surface is defined relative to it | evidenced Critical / Important | blocking set empty → Step 8 merge; non-empty → Step 6 fix, then Round 2 |
| Round 2 | only `baseline..HEAD` (the commits this round's fixes added) | evidenced Critical only | blocking set empty → merge; non-empty → circuit breaker (human adjudication) |
| Round 3 | **does not exist** — the loop never starts a third round | — | — |

Recording the baseline SHA in Round 1 is load-bearing: the `baseline..HEAD` surface cannot be
computed without it. The two surfaces are **disjoint** (`base..baseline` vs `baseline..HEAD`) —
neither contains the other, and Round 2's size is not bounded by Round 1's. Termination is
guaranteed by the two-round cap **alone**, never by the review surface changing size between rounds
(an earlier design claimed the surface shrinks each round; that was false — see problem-frame.md).

Re-run Step 3 on the round's review surface, then run Step 4 only if the Step 3.4 gate activates it.

**7.1 Refresh diff state** (required — diff has changed after fixes):

Re-run `setup-review-dir.sh` — it is the sole owner of the safe base resolution
(`git fetch` from the base remote — `upstream` if present, else `origin`, issue #196 — plus
`FETCH_HEAD`, so neither a stale local base nor a stale fork `origin` can silently poison the
diff; PR #22 + #196 lessons) and rewrites both `diff.patch` and `changed-files.txt`. Do **not**
hand-roll `git diff "{{base_branch}}"...HEAD` here — that uses the local ref and bypasses the fetch.

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/setup-review-dir.sh {{base_branch}}
```

**7.2 Apply the R2 activation gate**: all active voices re-run R1 to catch regressions. Recompute
candidate blockers and disputes from the new R1; previous voice verdicts have no gate authority. If
Step 3.4 skips R2, delete every stale R2 file before Step 5 aggregation:

```bash
WT_ROOT=$(git rev-parse --show-toplevel)
REVIEW_DIR="$WT_ROOT/.pr-review"
rm -f "$REVIEW_DIR/claude-r2.md" "$REVIEW_DIR/codex-r2.md" "$REVIEW_DIR/gemini-r2.md"
```

If the gate activates R2, run it for every active voice so debate participants see the same R1 set.

#### Baseline freshness (before Round 2 defines its surface)

Before Round 2 computes `baseline..HEAD`, confirm the baseline is fresh. A stale fork `origin` or a
cached `codex review --base` result silently distorts that surface with **no error** (CLAUDE.md
records both). `setup-review-dir.sh` already fetches from the base remote (`upstream` if present,
else `origin`) — do not bypass it with a hand-rolled local-ref diff.

#### Merge gate

Merge is gated **only** by the blocking set (Round 1 evidenced Critical / Important; Round 2
evidenced Critical). When that set is empty the PR merges even with open Actionable NITs or deferred
evidence-less findings still listed — NIT never blocks merge in any round, and neither does a
finding that carries no valid `Evidence:`.

#### Convergence condition

The **blocking set is the sole LGTM gate** after contract compliance is confirmed: every Acceptance
Criterion has verification evidence, no unauthorized scope drift remains, and material risks are
fixed or human-accepted within their documented boundary. A raw voice verdict has no independent
veto when it contains only non-blocking items. Actionable NIT, evidence-less, outside-contract, and
accepted-risk findings never re-open the loop. Round 1 blocking set non-empty → Step 6, then Round 2.

#### Circuit breaker

**Round 2 ends with a non-empty blocking set** → stop; do not start a third round. Hand the
unresolved findings to the user for adjudication, reusing the same three-option UX:

```text
Round 2 finished with unresolved blocking findings. Remaining items:
1. <Voice X>: <finding> — Critical
2. <Voice Y>: <finding> — Important, raised in Round 1

Possible causes:
- False positive (Voice X lacks sufficient codebase context)
- Needs more fix time (this is actually a large refactor)
- Return to re-design PR (scope too large)

Choose: [False positive / Continue fixing / Return to redesign]
```

Wait for explicit instruction before continuing.

#### Gotcha: re-review must not use stale diff.patch

A single-voice re-run after fixes **must** review the diff.patch that Step 7.1 refreshed, not the setup-stage version:

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/setup-review-dir.sh {{base_branch}}
bash ~/.agents/skills/pr-cycle-deep/scripts/codex-r1-stage1.sh
```

Never hand-roll it: `git diff "{{base_branch}}"...HEAD > diff.patch` uses the local ref and bypasses
the fetch (stale base, PR #22); `codex review --base` rejects the guard prompt and re-opens the
skill-hijack hole (issue #194); overwriting `codex-r1.md` directly destroys aggregate history (let
Stage 2 + Stage 3 render it from `codex-r1-raw.md`).

---

### Step 8 — Human quick pass

After the contract LGTM gate passes, the lead gives the human a summary **scannable in a few minutes**:

```bash
git diff "{{base_branch}}"...HEAD --stat
```

Write `$REVIEW_DIR/human-summary.md` with the Write tool:

```text
# Human Quick Pass — PR #{{pr_number}}

## What changed (one-page summary)
- Main functionality: ...
- Change scope: N files +X/-Y lines
- New tests: ...

## Key decisions handled during group review
1. <Consensus Critical 1>: fix approach = ...
2. <Disputed item>: user chose ___, reason ...

## Raw voice verdict (informational; no independent veto)
- Claude: LGTM / NEEDS_CHANGES (<blocking or non-blocking only>)
- Codex: LGTM / NEEDS_CHANGES / N/A
- Gemini: LGTM / NEEDS_CHANGES / N/A

## Change hotspots (top 3 places most worth human eyes)
1. <file:line> — <why it's a hotspot>
2. ...
```

Show the summary and hotspots to the user. Get the path, then reply conversationally so they can `cat` it:

```bash
WT_ROOT=$(git rev-parse --show-toplevel)
REVIEW_DIR="$WT_ROOT/.pr-review"
echo "$REVIEW_DIR/human-summary.md"
```

Reply (substitute the echoed path for `<path>`): "Contract satisfied and blocking set empty. Three hotspots in `<path>`. Raise concerns here — I (reviewer lead) respond immediately;
reply 'ship' to proceed to Step 9 CI."

User raises a concern → lead responds directly (citing R1/R2 original findings if needed); unresolvable concern → return to Step 6 to fix; resolved → user replies "ship" before proceeding to Step 9.

---

### Step 9 — CI Check

Wait for GitHub Actions to pass:

```bash
gh pr checks "{{pr_number}}" --watch
```

CI fails: reproduce locally (using CI command from Step 6) → fix → commit + push → wait again.
Local CI is authoritative: when CI and local differ, trust local; check for CI environment differences.

---

### Step 10 — Merge

### Pre-merge check: version bump

Before `gh pr merge`, ask the user whether this change needs a version bump (pre-evaluate first):

| Change type | Recommendation |
| --------- | ------ |
| Pure internal refactor, tests, CI config | Usually no bump |
| Bug fix, doc fix, performance, compatibility | patch |
| New feature, new API (backward-compatible) | minor |
| Breaking change (API-incompatible) | major |

- **Yes** → run [`/bump-version`](../bump-version/SKILL.md) first (commits version files + CHANGELOG + tag + push on the feature branch), then **wait for the new CI run to go green**
  before returning. After `--squash` merge the tag points at the feature-branch HEAD, not the main merge commit — re-tag on main if you need it there.
- **No** → confirm and proceed.
- **Unsure** → describe the change; agent suggests a bump type and **waits for confirmation**.

Only merge after the user says "no bump" or "I've run `/bump-version`". If bumped, confirm the
release commit and tag both reached remote (commit push and tag push are independent — tags silently fail to push):

```bash
git fetch
```

```bash
git log --oneline -3 '@{upstream}'
```

One of the last 3 commits must match `chore(release): v*`; extract its tag (e.g. `v1.2.3`) and confirm the tag is on remote (empty → prompt the user to run `git push --tags`):

```bash
git ls-remote --tags origin 'refs/tags/v<TAG_VERSION>'
```

> **If the target repo has tag-triggered CI/CD** (auto GitHub Release on tag push): the tag is pushed before the merge and may trigger a production deploy. Evaluate the risk, or re-tag on main after merging.

---

```bash
gh pr merge "{{pr_number}}" --squash --delete-branch
```

> **If a protect-push (or similar) PreToolUse hook blocks `gh pr merge`**: the agent cannot
> merge in such repos. Ask the user to run it themselves:
> `! gh pr merge {{pr_number}} --squash --delete-branch` — and from the **main repo
> directory**, not a linked worktree (worktree merge fails with
> `'main' is already used by worktree`).

```bash
gh pr view "{{pr_number}}" --json mergeCommit -q .mergeCommit.oid
```

Note the SHA as `{{merge_commit_sha}}` and report it to the user.

---

### Step 11 — Spectra Archive + Jira Sync (wrap-up, optional)

Both sub-sections are **optional** — skip if no spectra change or no Jira issue.

#### 11a — Spectra Archive

No spectra change created → skip. Otherwise:

```bash
spectra list
```

Find the matching change (name is usually close to the feature branch), **report the name to the user and wait for confirmation before archiving** (archive is irreversible, Rule 15):

> Found a likely matching spectra change: `{{change_name}}`. Confirm archive?

After confirmation:

```bash
spectra archive "{{change_name}}" --yes
```

Non-zero exit → stop and report. Validation has Critical errors → run `spectra analyze {{change_name}}` to find the issue, fix it, then archive; `--no-validate` requires explicit user instruction.

#### 11b — Jira Sync

Branch was deleted by `--delete-branch`; extract Jira key from PR title / body:

```bash
gh pr view "{{pr_number}}" --json title,body -q '.title + " " + (.body // "")'
```

Output has no `[A-Z]{2,}-[0-9]+` format string → ask the user, or skip 11b.

Get transitions (sequential, then parallel):

- `mcp__claude_ai_Atlassian__getTransitionsForJiraIssue` (`issueId`: `{{jira_issue_key}}`)
  If the call fails, stop and report the error to the user.

Pick the option closest to "development complete and merged" (common: `Done` / `Merged` / `Released` / `Closed`). If unsure, ask the user.

After confirming, **send in parallel** (no dependency); either failure must be reported
and must not be silently ignored:

- `mcp__claude_ai_Atlassian__transitionJiraIssue`: move `{{jira_issue_key}}` to selected state
- `mcp__claude_ai_Atlassian__addCommentToJiraIssue`: comment content:

```text
PR #{{pr_number}} squash-merged to main.
Merge commit: {{merge_commit_sha}}
Group review mode: {{N}}/3 voices active; Review Contract satisfied and blocking set empty.
```

If 11a archived a change, append:

```text
Spectra change `{{change_name}}` archived; spec status updated to complete.
```

Report back to the user: spectra archive status, Jira ticket status.

> **Suggested next step**: run `/pr-retro` to close out this session; the agent drafts 5 questions from the PR context for your calibration.

---

## Troubleshooting

<!-- KEEP IN SYNC WITH ../pr-review-cycle/SKILL.md (same FAQ row for pr-test-analyzer anti-patterns). If you update one, update both. -->

| Issue | How to handle |
| --- | --- |
| How to avoid the three pr-test-analyzer traps (fake test / presence-only / no-CI)? | Three anti-patterns to always check: (1) **Fake test** (inverse of mutation testing) — the test case logic has a silent bug; all cases PASS but some test action never fires (e.g. env-var override test takes the unset branch; empty value not actually exported, so it runs the same path as another case); "all green" masks a scenario never tested. Fix: mutation testing intuition — intentionally break one production line and check whether that test case **really** fails; if not, it's a fake test. (2) **Presence test ≠ contract test** — `grep function_name` confirming the function is called is the weakest form; if the invariant is "the function must be called **with the correct args**" (e.g. the deploy script must call the guard helper with the **correct default context**), the test must verify the full contract (`function_name <expected_arg>` paired), not just function name presence. (3) **Test not wired to CI = half-finished test** — submitting a test file with no CI / pre-commit / git-hook / `make test` trigger means regressions are only caught when an operator manually runs tests; operators rarely do this spontaneously. Fix: "wired to CI?" should be listed alongside "what to test" and "how to test" as the three required test-design elements. Choose the mechanism per tech stack: Python repos use pre-commit local hook + `files:` regex; TS/JS use husky / lefthook; Go / Rust use `make test` + CI workflow `step: run: make test`. Common requirement: changing production code triggers tests automatically. |
| Cache hit but a cached-available voice's auth now fails | Step 0a re-verifies auth on every warm-path run; on `NOT_AUTHED` / `KEY_WHITESPACE_PREFIX` it stops and shows the fix command — re-auth, then re-run Step 0b (refreshes the cache). The static check cannot see a present-but-expired token; that case is caught at use-time by the R1 fail-loud (`agy_validate.py` / codex error) |
| Want to force full re-detection (new voice configured, cache predates it) | Delete `~/.claude/mob-detection-cache` and re-run — Step 0a falls through to full Step 0b detection |
| Step 0 zero available (all NOT_FOUND or auth failed) | This skill terminates; run `/pr-review-cycle` instead (Claude-only is sufficient) |
| Step 0 detects `KEY_WHITESPACE_PREFIX` | Key has a leading space (e.g. copied from terminal); run `export CODEX_API_KEY="${CODEX_API_KEY# }"` or the corresponding key name to strip leading space, then re-run Step 0 |
| `GEMINI_AUTH: NOT_AUTHED` (agy not configured) | Run `agy` to complete browser OAuth; `onboarding.json`'s `onboardingComplete` will become true; or `export GEMINI_API_KEY=...` |
| Step 0 detects only Codex (no agy) | Enter 2-voice mob (Claude + Codex); normal workflow |
| Step 0 detects only agy (no Codex) | Enter 2-voice mob (Claude + agy); normal workflow |
| Codex detected but auth failed | `codex login`; or `export OPENAI_API_KEY=...` |
| agy detected but auth failed | Run `agy` to complete OAuth; or `export GEMINI_API_KEY=...` |
| agy went agentic in a nested worktree (wrong-target review / brain-artifact pointer / `Error: timed out`) | issue #153: agy could not resolve `@file` and entered agentic file-search. The agy scripts now **inline** the prompt (no `@file`), clear stale `~/.gemini/antigravity-cli/scratch/gemini-*-input.md` at start, and run `agy_validate.py` (fail-loud: timeout / agentic narration / missing Verdict / mentions no changed file = wrong target; a `brain/<uuid>/*.md` pointer is auto-rescued into the raw file). If `agy_validate.py` exits non-zero the voice is correctly marked failed — read the `[FAIL]` message for the reason |
| agy background bash `>` redirect output not updating target file (unverified) | If this occurs: switch to synchronous bash call (without `run_in_background`) |
| Codex Stage 1 `codex-r1-raw.md` is empty (review missing) | Stage 1 now uses `codex exec ... > codex-r1-raw.md` (stdout); read `$REVIEW_DIR/codex-r1.stage1.log` (stderr) for the error. For the `codex exec \| tee` stages (Stage 2 / R2), `set -o pipefail` keeps `$?` reflecting the failing command in the pipeline (bash/zsh) |
| Why Stage 1 uses `codex exec`, not `codex review --base` + a guard prompt | `codex review --base` and a positional `[PROMPT]` are mutually exclusive (codex-cli 0.142.5: `the argument '[PROMPT]' cannot be used with '--base <BRANCH>'`), so the skill-hijack guard cannot ride on `codex review`. Stage 1 drives the review through `codex exec` with the guard on stdin instead (issue #194). Do not "fix" it back to `codex review --base` |
| codex Stage 1 runs against wrong repo | The stage-1 script passes `codex exec -C "$WT_ROOT"`, pinning the repo root; ensure you run the script from inside the worktree (avoid tools like gstack changing CWD, AP3 Sub-class A) |
| A voice fails R1/R2 twice consecutively | Mark as unavailable; do not block; aggregate report notes the reason |
| R2 receives r1-aggregate that is too large for voice to process | Remove raw diff from r1-aggregate; keep only findings; diff was already processed in the r1 prompt |
| Round 2 ends with unresolved blocking findings | Trigger circuit breaker; hand remaining findings to user with the three-option decision (no third round) |
| User chooses to ignore a disputed finding | Add a Known Issues section to the PR description with the reason |
| User raises new concern during human quick pass | Reviewer lead (Claude main) responds immediately; unresolvable → return to Step 6; resolved → wait for user "ship" |
| When does R2 run? | All active voices always run independent R1. Run R2 only when Step 3.4 finds a candidate blocker or blocking dispute; a clean R1 reports the required skip message and aggregates directly. |
| Linter / type-check fails | `ruff check --fix` / `eslint --fix` / `mypy follow_imports = skip` etc. |
| Security scanner fails | bandit `# nosec BXXX` etc. ignore comments; explain reason in PR |
| spectra archive validation fails | `spectra analyze {{change_name}}`; fix then archive; `--no-validate` requires explicit user instruction |
| Cannot detect Jira key | Ask user to provide (format: `PROJECT-123`), or confirm no associated ticket and skip |
| Jira transition options unclear | List all transitions and ask user to confirm |
| Jira MCP auth error | Atlassian MCP requires OAuth; prompt user to authorize on claude.ai |
| Codex extract returns invalid JSON | Follow Stage 3 if/else branch: Read `$REVIEW_DIR/codex-r1-raw.md`, manually summarize in main context as compact markdown, Write to `$REVIEW_DIR/codex-r1.md`; note in final.md "Codex voice used raw form this round, main context load higher" (do not cp raw → compact directly; verbose raw would enter r1-aggregate) |
| Gemini extract JSON doesn't match schema | Same as above; manually summarize `$REVIEW_DIR/gemini-r1-raw.md` → `$REVIEW_DIR/gemini-r1.md` (do not cp) |
| Extract step keeps failing (2 consecutive) | Fall back to path C: Claude lead reads raw with Read tool, manually extracts compact form in main session without calling codex/agy again; less efficient but workflow not blocked |
| Extract prompt path missing (`~/.agents/skills/pr-cycle-deep/prompts/extract-r1.md`) | Skill not installed; run `make install` in the yibi-stack directory to create the symlink; verify: `ls ~/.agents/skills/pr-cycle-deep/prompts/extract-r1.md` should return the path, not "No such file" |
| User skipped bump but needs a version tag later | Create a release branch, run [`/bump-version`](../bump-version/SKILL.md) on it, then open a PR to merge into main (CI pass + CHANGELOG confirmed is sufficient; no full review cycle needed; if main has new commits, CHANGELOG may include extra entries — verify manually) |
