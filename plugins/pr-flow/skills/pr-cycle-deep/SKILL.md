---
name: pr-cycle-deep
type: know
scope: global
description: >
  Mob review by multiple frontier-model agents — 完整 PR 生命週期含跨家 LLM
  group review：自動偵測 codex / agy，≥1 家即啟動
  R1 獨立 + R2 交叉 debate + aggregate；fix → re-review 直到全員 LGTM（含
  actionable NIT）→ 人類快速複查 → CI → merge → spectra archive + Jira sync。
  適用中大型 PR / 高風險改動 / 跨家視角壓力測試 / SDD 專案。小型 PR 或快速 lifecycle
  請改用 `/pr-cycle-fast`（Claude-only state machine）。純 PR review 不需完整 lifecycle
  請改用 `/pr-review-cycle`（4 個 pr-review-toolkit subagent 平行）。
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

**Core philosophy**: when codex / agy are detected, run them alongside Claude as **synchronous
parallel** reviewers — each reviews independently, then cross-reads each other's findings to
debate, and produces an aggregated final report. The coding agent (Claude main session) fixes
according to the report, then runs another round of group review, cycling until all reviewers
LGTM (including actionable NITs). Finally, the human scans all changes in a few minutes, raises
concerns immediately, and the reviewer lead (Claude main) responds on the spot — faster than
finding two senior engineers, and broader in perspective.

No external models detected → prompt the user to fall back to `/pr-review-cycle`; this skill terminates (no fallback inside `/pr-cycle-deep`, to avoid semantic confusion).

## Usage

```text
/pr-cycle-deep
/pr-cycle-deep #<PR number>   ← skip to Step 2 if PR already exists
```

---

## Step 0 — Reviewer Detection (determine workflow mode)

### Step 0a — Read detection cache

First use the Read tool to try reading `~/.claude/mob-detection-cache`:

- **File exists**: report cache contents and ask the user:

  ```text
  [Cache] Last detection result ({{DATE}}):
  - Codex:  ✓ / ✗
  - Gemini (agy): ✓ / ✗
  - Mode: {{MODE}}

  Use cache and go directly to Step 1? (y / n=re-run detection)
  ```

  User replies y → skip Step 0b, go directly to Step 1.
  User replies n → run Step 0b (re-detect and update cache).
- **File does not exist** (Read tool returns error): run Step 0b directly.

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

**`BINARY_OK + NOT_AUTHED` handling**: binary found but auth failed (`NOT_AUTHED`,
`KEY_WHITESPACE_PREFIX`) does not count as "available", and Step 0 **must explicitly stop**
rather than silently counting this tool as one fewer available — otherwise the user assumes
the tool is not installed, rather than that auth is broken. When this state is detected, show
the user the fix command, and re-run Step 0 after they confirm the fix.

**Note**: the count table below only applies when all binary-OK tools have passed auth.
If any tool shows `BINARY_OK + NOT_AUTHED / KEY_WHITESPACE_PREFIX` → do not enter the
count calculation; show the user the fix command and wait for them to confirm the fix,
then re-run Step 0.

| Available external reviewers | Action |
| ---: | --- |
| 0 (all NOT_FOUND, no auth failures) | **Fall back to `/pr-review-cycle`** (Claude-only is sufficient; this skill terminates) |
| **1** (Codex or Gemini) | **2-voice mob** (Claude + 1 external; cross-model debate is already meaningful) |
| **2** (Codex + Gemini) | **3-voice full mob** (broadest coverage) |

Report detection results to the user and wait for confirmation before continuing:

```text
Detection results:
- Claude  ✓ always available (pr-review-toolkit)
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
| **MAY** | Actionable NIT | Optional per RFC 2119 — but this skill's convention cleans up every **undisputed actionable NIT** before merge (see Step 5) |

MUST = functional / security / PII-in-logs / data-loss / explicit-baseline violation.
SHOULD = test gaps on changed critical paths, silent failures, naming / structure
inconsistency, misleading docs. MAY = concrete, actionable small fixes: naming, comment typo, import order, small documentation clarification.
Subjective preference with no verifiable reason is **not a finding** — discard it.

---

## Workflow (mob review mode)

### Step 1 — Create PR

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

Write the PR body to `/tmp/pr-body.md` with the Write tool (avoids heredoc triggering hooks), then pass it in:

```bash
gh pr create --title "..." --body-file /tmp/pr-body.md
```

```bash
rm -f /tmp/pr-body.md
```

If the project has `/commit-commands:commit-push-pr` slash command installed, run that directly (auto commit + push + PR).

Note the PR number as `{{pr_number}}` and the base branch as `{{base_branch}}` (usually `main`).

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

Run `/code-review` to scan all PR changes for correctness bugs:

```text
/code-review
```

For stricter review, specify effort:

```text
/code-review high
```

Optional: add `--comment` to post findings directly as GitHub PR inline comments:

```text
/code-review --comment
```

- **No findings** → proceed to Step 3.
- **Has findings** → bring into Step 6 (Fix) and handle together with mob review results.
  `/code-review` **does not modify code**; findings are review comments and do not need a separate commit.

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

Write all R1/R2 intermediate files to the review dir (`<worktree-root>/.pr-review/`, referred
to as `$REVIEW_DIR`). Using the worktree root as namespace naturally isolates concurrent sessions;
re-running review in the same worktree naturally overwrites old output.
`agy` `@file` requires the path to be within the `--add-dir` allowlist; this skill puts all
intermediate files in `<worktree-root>/.pr-review/` and authorizes with `--add-dir "$WT_ROOT"`,
avoiding `/tmp/` paths being rejected by the sandbox.

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/setup-review-dir.sh {{base_branch}}
```

The script's last line outputs `REVIEW_DIR=<absolute path>` as informational; subsequent bash
calls do not need to parse this output — derive directly from the worktree root
(`WT_ROOT=$(git rev-parse --show-toplevel); REVIEW_DIR="$WT_ROOT/.pr-review"`, equivalent).

**Why extracted to a script**: the original fat bash block violated rule 13 AP1 (overly complex
single command), rule 14 Quoting Rule 5 (multiple `"$VAR"` expansions), rule 14 `$?` section
(`if [ $? -ne 0 ]`), and writing to `.git/info/exclude` triggered a permission dialog.
The script uses `set -euo pipefail` and `if ! cmd; then` instead of `$?`, and validates
`BASE_BRANCH` with `git rev-parse --verify` before entering git diff
(to avoid typos leaving a 0-byte diff.patch).

**Allow-list pattern note**: `Bash()` rules do **not expand** `~` (rule 16 "safe pattern
examples", key point 2), so `Bash(bash ~/.agents/skills/.../setup-review-dir.sh)` **does not**
match the runtime string. When permanently allowing in `~/.claude/settings.local.json`, use
the expanded absolute path:

```text
Bash(bash /Users/<you>/.agents/skills/pr-cycle-deep/scripts/setup-review-dir.sh *)
Bash(bash /Users/<you>/.agents/skills/pr-cycle-deep/scripts/codex-r1-stage1.sh *)
```

Confirm `<you>` with `whoami` or `echo $USER`. Full absolute path + trailing `*` matches rule 16 safe pattern (script is already reviewed; `*` only expands to branch name argument).

The extract prompt path is fixed at `~/.agents/skills/pr-cycle-deep/prompts/extract-r1.md` (symlink created by `make install`); no need to resolve `SKILL_REPO`.

Write the review prompt to `$REVIEW_DIR/prompt-r1.md` using the Write tool (`$REVIEW_DIR` is
the actual path derived above, e.g. `/path/to/worktree/.pr-review`). Replace `{{REVIEW_DIR}}`
with the actual `$REVIEW_DIR` value before writing:

```text
You are a senior code reviewer. Review the following PR diff independently.

Base branch: {{base_branch}}
PR #: {{pr_number}}
Diff: see {{REVIEW_DIR}}/diff.patch
Changed files: see {{REVIEW_DIR}}/changed-files.txt

Output format (strictly follow, for downstream aggregation):

## Summary
<1-2 sentence overall assessment>

## Findings

### [Critical] <short title>
- File: <path:line>
- Issue: <description>
- Suggested fix: <how to fix>

### [Important] <short title>
...

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
- Do NOT list "code style preferences" or "subjective aesthetics" — non-actionable items only
- Be skeptical, be terse, no compliments
```

#### 3.2 — Launch 3 voices in parallel

**In the same message**, send all reviewer calls in parallel (only send available voices):

##### Claude voice (pr-review-toolkit 4 subagents)

Launch four Task subagents in parallel (each produces independent findings; the lead merges them into the Claude voice):

| Subagent | Focus |
| --- | --- |
| `code-reviewer` | Convention compliance, bugs, logic errors |
| `silent-failure-hunter` | Silent failures, swallowed exceptions |
| `pr-test-analyzer` | Test coverage gaps |
| `comment-analyzer` | Documentation / comment accuracy |

After all four complete, the lead uses the Write tool to merge them into `$REVIEW_DIR/claude-r1.md` (following the output format above).

##### Codex voice (when CODEX_OK)

###### Stage 1: Native review (raw output lands on disk, does not enter main context)

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/codex-r1-stage1.sh {{base_branch}}
```

`codex review` does not support the `-C` flag; run from the correct cwd. `--base` and
positional prompt are mutually exclusive; codex's built-in review mode automatically generates
[P1]/[P2] grading. Raw output lands in `codex-r1-raw.md` — **do not read it in the main context**.

###### Stage 2: Extract (compress verbose raw markdown into structured JSON)

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/codex-r1-stage2.sh
```

###### Stage 3: Render (lead reads JSON → writes compact markdown)

Lead reads `$REVIEW_DIR/codex-r1.json` with the Read tool and branches on the result:

**JSON valid** (valid JSON with `verdict` / `summary` / `findings` fields) → use the Write tool to render `$REVIEW_DIR/codex-r1.md` (compact markdown, sorted by severity: critical → important → actionable_nit).

**JSON invalid** (not valid JSON or missing fields) → immediately execute fallback, do not attempt to render:

1. Read `$REVIEW_DIR/codex-r1-raw.md` with the Read tool and manually summarize in the main context
2. Write compact markdown to `$REVIEW_DIR/codex-r1.md` with the Write tool
3. Note in the final final.md: "Codex voice used raw form this round; main context load is higher"

Format example (compact markdown):

```text
## Codex R1

**Verdict**: NEEDS_CHANGES
**Summary**: <summary field>

### [critical] <title>
- File: <file>:<line_start>-<line_end>
- Issue: <issue>
- Fix: <fix>

### [important] <title>
...
```

##### Gemini voice (when GEMINI_OK)

agy does not accept a combined stdin prompt + diff path; concatenate into a single file first:

###### Stage 1: Native review (raw output lands on disk, does not enter main context)

> **[Important] bash block execution rules**:
>
> - Execute the bash block below verbatim; **do not add any `$?`-related code after the agy command**
>   (including `echo "exit:$?"` or additional `if [ $? -ne 0 ]`) —
>   Rule 5: the parser intercepts ALL `simple_expansion` nodes; `$?` triggers a confirmation dialog
>   regardless of quoting; the bash block already contains exit code handling, do not add more
> - **`@file` triggers agentic mode (PR #303 lesson)**: `agy -p "@/abs/path" > out.md` in redirect mode
>   may cause agy to enter agentic tool call mode — the model outputs `call:read_file{...}` text
>   instead of actual review content. How to confirm: if `gemini-r1-raw.md` starts with `call:` or
>   `tool_use:` → agentic mode triggered.
> - **Stage 1 uses `--dangerously-skip-permissions` (BS-001)**: `--sandbox` **blocks** `@file` reading
>   in Stage 1 full review tasks (agy enters agentic mode, outputs `call:read_file{...}` instead of
>   review content). Field-tested: `agy-r1-stage1.sh` with `--dangerously-skip-permissions` outputs
>   review text correctly. **Only Stage 2 extraction can use `--sandbox`** (extraction tasks behave
>   differently and do not trigger agentic mode).
> - **[Security] `--dangerously-skip-permissions` trust boundary**: Stage 1 scripts remove agy tool
>   access restrictions. If the PR diff comes from an external fork or untrusted source, malicious
>   instructions in the diff may be auto-approved by agy (prompt injection risk). This skill assumes
>   the PR comes from a trusted repo; when running mob review on an external fork, the operator must
>   evaluate this risk themselves.
> **Execution note**: the script writes stderr to `$REVIEW_DIR/gemini-r1.stage1.log`; stdout only
> outputs "agy R1 Stage 1 complete". **Run directly — do not append `> $CLAUDE_JOB_DIR/foo.log 2>&1`**
> (harness auto-capture is redundant here; see rule 16 **(2) Bash redirect `>`** for `Bash(verb:*)` allow-list patterns) —
> on failure, Read `$REVIEW_DIR/gemini-r1.stage1.log` for the full error.

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/agy-r1-stage1.sh
```

`agy` automatically selects the best model (no `-m` flag needed). To pin a model, set
`defaultModel` in `~/.gemini/antigravity-cli/settings.json`. Raw output lands in
`gemini-r1-raw.md` — **do not read it in the main context**.

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

### Step 4 — Round 2: Cross-debate

**Goal**: each voice reads the other voices' R1 findings and takes positions (agree / disagree / supplement), forcing out consensus and disputes.

#### 4.1 — Generate R1 aggregate

Use the Write tool to concatenate all R1 content into `$REVIEW_DIR/r1-aggregate.md` (only
include voices that produced output). Replace `$REVIEW_DIR` with the actual path
(e.g. `/path/to/worktree/.pr-review`) and paste each voice's compact markdown in full:

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

> **Security note**: `agy-r2.sh` uses `--sandbox`; assumes PR comes from a trusted repo.
> For external fork PRs, the operator should evaluate prompt injection risk and may remove this flag to use interactive mode.

Only send to available voices (CODEX_OK / GEMINI_OK).

Claude voice: the lead writes `$REVIEW_DIR/claude-r2.md` after reading r1-aggregate — no subagents needed (avoid 4×4 = 16 reviews generating too much noise).

---

### Step 5 — Aggregator synthesis

After the lead reads all R1 + R2, produce `$REVIEW_DIR/final.md`, graded per the
[Review Severity Standard](#review-severity-standard-rfc-2119) (Critical = MUST, Important =
SHOULD, Actionable NIT = MAY). Note the project override: although **MAY** is optional under
RFC 2119, this skill's convention cleans up every actionable NIT before merge (see the
Actionable NIT row).

| Grade | Condition | Action |
| --- | --- | --- |
| **Consensus Critical** | ≥2 voices mark Critical with no DISAGREE | Must fix |
| **Consensus Important** | ≥2 voices mark Important with no DISAGREE | Must fix |
| **Disputed** | 1 voice marks Critical/Important; others DISAGREE | List the dispute; user decides |
| **Single-voice Critical** | 1 voice marks Critical; others did not mention | Lead evaluates: technically sound → elevate to Consensus; otherwise list as Disputed |
| **Actionable NIT** | Any 1 voice marks NIT and it's not subjective preference | **Must fix** (user emphasized "all NITs cleaned up") |
| **Withdrawn** | Marked WITHDRAW in R2 | Remove from list |
| **Voice unavailable** | That voice failed R1/R2 twice in a row | Note in final.md; do not block |

`final.md` format:

```text
# Final Aggregated Review — PR #{{pr_number}}

## Mode
group-review ({{N}}/3 voices active)

## Consensus Critical (must fix)
1. <finding>...

## Consensus Important (must fix)
1. <finding>...

## Actionable NIT (must fix — user requires all NITs cleaned up)
1. <finding>...

## Disputed (user decides)
- Voice X argues Critical: <reason>
- Voice Y disagrees: <reason>
- Lead recommendation: <decision guidance>

## Voices unavailable
- <voice>: <reason>
```

Report the final.md summary to the user and wait for Disputed item decisions before proceeding to Step 6.

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

---

### Step 7 — Group re-review (until all voices LGTM)

Re-run Step 3 + Step 4 (R1 + R2) on **files modified in this round**.

**7.1 Refresh diff state** (required — diff has changed after fixes):

```bash
WT_ROOT=$(git rev-parse --show-toplevel)
REVIEW_DIR="$WT_ROOT/.pr-review"
mkdir -p "$REVIEW_DIR"
git diff "{{base_branch}}"...HEAD > "$REVIEW_DIR/diff.patch"
git diff "{{base_branch}}"...HEAD --name-only > "$REVIEW_DIR/changed-files.txt"
```

**7.2 Token savings: only skip R2 debate for voices that were LGTM in the previous round** (R1 still runs for all):

Read each voice's **most recent** verdict file (prefer `*-r2.md`; fall back to `*-r1.md`) and
find voices with `Final verdict: NEEDS_CHANGES` (R2 format) or `## Verdict` section containing
`NEEDS_CHANGES` (R1 format).

- **All voices**: re-run R1 (confirm new fixes haven't introduced regressions)
- **Previous-round NEEDS_CHANGES voices**: run R1 + R2
- **Previous-round LGTM voices**: run R1 only; skip R2 debate (saves one API round-trip; LGTM voices' R2 is a cross-check on old findings, which no longer exist this round)

```text
Re-run decision logic (agent executes):
- claude   previous-round NEEDS_CHANGES → R1 + R2
- codex    previous-round LGTM          → R1 only (skip R2, save one codex exec)
- gemini   previous-round NEEDS_CHANGES → R1 + R2
```

New-round R1 overwrites old R1 files (all voices); R2 only overwrites voices that needed re-running.

**LGTM voices' old R2 handling (important)**: for voices that skip R2, their old `*-r2.md`
still exists on disk, but **must not be referenced in this round's aggregation** — old R2
corresponds to a previous diff and the content may be stale. Before running Step 5 aggregation,
delete old R2 files for LGTM-skip voices:

```bash
WT_ROOT=$(git rev-parse --show-toplevel)
REVIEW_DIR="$WT_ROOT/.pr-review"
# LGTM voice skipping R2: delete old r2 before aggregation to avoid stale results
# Replace voice names with the actual voices skipping this round (codex / gemini / claude)
rm -f "$REVIEW_DIR/codex-r2.md"   # if codex is LGTM-skip this round
```

If a LGTM voice shows NEEDS_CHANGES in new R1, immediately run R2 (r2 file was deleted; re-running overwrites it).

#### Convergence condition

**All voices LGTM** = every active voice in the latest round outputs:

- `Final verdict: LGTM`, and
- no new [Critical] / [Important] / [Actionable NIT] findings

Any voice still has actionable items → return to Step 6 to fix.

#### Circuit breaker

After **3 consecutive rounds** without all voices LGTM → stop automatic retries; present the user with the persistent unresolved findings:

```text
Group review has run 3 rounds without all voices LGTM. Remaining unresolved items:
1. <Voice X>: <finding> — Critical for 3 consecutive rounds
2. <Voice Y>: <finding> — raised in round 2

Possible causes:
- False positive (Voice X lacks sufficient codebase context)
- Needs more fix time (this is actually a large refactor)
- Return to re-design PR (scope too large)

Choose: [False positive / Continue fixing / Return to redesign]
```

Wait for explicit instruction before continuing.

#### Gotcha: re-review must not use stale diff.patch

When manually triggering a single voice re-run after fixes, the input **must use the diff.patch refreshed in Step 7.1**, not the stale version from the setup stage:

```bash
# Correct: re-run codex using codex review native mode (reads git diff automatically); use round number in output name
WT_ROOT=$(git rev-parse --show-toplevel)
REVIEW_DIR="$WT_ROOT/.pr-review"
codex review --base "{{base_branch}}" -c 'model_reasoning_effort="high"' 2>"$REVIEW_DIR/codex-rerun.log" | tee "$REVIEW_DIR/codex-r2-r1.md" > /dev/null

# Wrong 1: missing reviewer prompt -- codex exec doesn't know it's doing a code review
# Wrong 2: output directly overwrites codex-r1.md -- destroys aggregate history
# cat "$REVIEW_DIR/r1-aggregate.md" "$REVIEW_DIR/diff.patch" > "$REVIEW_DIR/codex-rerun-input.md"
# codex exec -C "$WT_ROOT" -s read-only < "$REVIEW_DIR/codex-rerun-input.md" > "$REVIEW_DIR/codex-r1.md"

# Wrong 3: prompt-r1.md is a reviewer prompt (for diffs), not aggregate; and diff.patch may be stale if not refreshed
# cat "$REVIEW_DIR/prompt-r1.md" "$REVIEW_DIR/diff.patch" > "$REVIEW_DIR/codex-final2-input.md"
```

---

### Step 8 — Human quick pass

After all voices LGTM, the lead gives the human a summary **scannable in a few minutes**:

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

## Voices final verdict
- Claude: LGTM
- Codex: LGTM (if CODEX_OK) / N/A
- Gemini: LGTM (if GEMINI_OK) / N/A

## Change hotspots (top 3 places most worth human eyes)
1. <file:line> — <why it's a hotspot>
2. ...
```

Show the summary and hotspots to the user and invite challenges. First get the actual path with bash, then communicate via conversational reply (so the user can directly cat the path):

```bash
WT_ROOT=$(git rev-parse --show-toplevel)
REVIEW_DIR="$WT_ROOT/.pr-review"
echo "$REVIEW_DIR/human-summary.md"
```

Then reply to the user (substitute the actual path from the echo above for `<path>`):

```text
All voices LGTM. Three hotspots listed in <path>.
Raise any concerns directly in this session; I (reviewer lead) will respond immediately.
No concerns? Reply "ship" to proceed to Step 9 CI check.
```

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

Before running `gh pr merge`, pause and ask the user:

> Does this change require a version bump?
>
> - **Yes** → run [`/bump-version`](../bump-version/SKILL.md) first (commits version files + CHANGELOG + git tag + push on the feature branch).
>   After that, **return to the previous step and wait for CI to go green** (new commit triggers a new CI run), then come back here to continue merging.
>   Note: after `--squash` merge the git tag points to the feature branch HEAD, not the main merge commit; if you need the tag on main, re-tag on main after merging.
> - **No** → confirm and proceed to merge.
> - **Unsure** → describe the change; the agent evaluates and suggests a bump type, then **waits for user confirmation** before running `/bump-version` or proceeding.

Decision guide (agent may pre-evaluate before asking):

| Change type | Recommendation |
| --------- | ------ |
| Pure internal refactor, tests, CI config | Usually no bump needed |
| Bug fix, doc fix, performance, compatibility | patch |
| New feature, new API (backward-compatible) | minor |
| Breaking change (API-incompatible) | major |

(This guide is for quick assessment only; full definition in [`/bump-version`](../bump-version/SKILL.md) Step 1.)

Only proceed to `gh pr merge` after the user explicitly says "no bump needed" or "I've run `/bump-version`".
If the user says "I've run `/bump-version`", confirm the bump commit was pushed to remote:

```bash
git fetch
```

```bash
git log --oneline -3 '@{upstream}'
```

Confirm that one of the last 3 commits matches `chore(release): v*` format; if not, prompt the user to complete `/bump-version` Step 4 (push) before continuing.
Extract the version tag from that commit message (e.g. `v1.2.3`) and confirm that tag was pushed to remote (commit push and tag push are independent operations; tags may silently not be pushed):

```bash
git ls-remote --tags origin 'refs/tags/v<TAG_VERSION>'
```

(e.g. `git ls-remote --tags origin 'refs/tags/v1.2.3'`)
Confirm the output contains the exact version tag, not just older tags; if empty, prompt the user to run `git push --tags`.

> **If the target repo has tag-triggered CI/CD** (e.g. automatic GitHub Release on tag push):
> the git tag is pushed before the merge and may trigger a production deployment. Evaluate the
> risk before continuing, or re-tag on main after merging instead.

---

```bash
gh pr merge "{{pr_number}}" --squash --delete-branch
```

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
Group review mode: {{N}}/3 voices LGTM (Claude / Codex / Gemini).
```

If 11a archived a change, append:

```text
Spectra change `{{change_name}}` archived; spec status updated to complete.
```

Report back to the user: spectra archive status, Jira ticket status.

> **Suggested next step**: run `/pr-retro` to close out this session; the agent drafts 5 questions from the PR context for your calibration.

---

## Reviewer Call Quick Reference

| Voice | Detection | R1 call (3-stage) | R2 call | Aggregate input |
| --- | --- | --- | --- | --- |
| Claude | always | Task() pr-review-toolkit 4 subagents | lead writes claude-r2.md directly | claude-r1.md (finding markdown) |
| Codex | `which codex` + auth | S1: `set -o pipefail; codex review --base $BASE 2>stage1.log \| tee codex-r1-raw.md > /dev/null` / S2: `codex exec low < extract-input 2>extract.log \| tee codex-r1.json > /dev/null` / S3: lead renders codex-r1.md | `set -o pipefail; codex exec -C "$WT_ROOT" -s read-only < input.md 2>r2.log \| tee codex-r2.md > /dev/null` | codex-r1.md (compact, not raw) |
| Gemini/agy *(optional)* | `which agy` + auth | S1: `bash agy-r1-stage1.sh` / S2: `agy -p @.pr-review/extract-input --add-dir . --sandbox > gemini-r1.json` / S3: lead renders gemini-r1.md | `bash agy-r2.sh` | gemini-r1.md (compact, not raw) |

Each voice's R1 / R2 should be written to `$REVIEW_DIR/<voice>-r{1,2}.md` (compact version),
read by the lead for unified aggregation. Raw versions (`*-r1-raw.md`) stay on disk for disputed
finding reference but **do not enter the main context**.

---

## Troubleshooting

<!-- KEEP IN SYNC WITH ../pr-review-cycle/SKILL.md (same FAQ row for pr-test-analyzer anti-patterns). If you update one, update both. -->

| Issue | How to handle |
| --- | --- |
| How to avoid the three pr-test-analyzer traps (fake test / presence-only / no-CI)? | Three anti-patterns to always check: (1) **Fake test** (inverse of mutation testing) — the test case logic has a silent bug; all cases PASS but some test action never fires (e.g. env-var override test takes the unset branch; empty value not actually exported, so it runs the same path as another case); "all green" masks a scenario never tested. Fix: mutation testing intuition — intentionally break one production line and check whether that test case **really** fails; if not, it's a fake test. (2) **Presence test ≠ contract test** — `grep function_name` confirming the function is called is the weakest form; if the invariant is "the function must be called **with the correct args**" (e.g. the deploy script must call the guard helper with the **correct default context**), the test must verify the full contract (`function_name <expected_arg>` paired), not just function name presence. (3) **Test not wired to CI = half-finished test** — submitting a test file with no CI / pre-commit / git-hook / `make test` trigger means regressions are only caught when an operator manually runs tests; operators rarely do this spontaneously. Fix: "wired to CI?" should be listed alongside "what to test" and "how to test" as the three required test-design elements. Choose the mechanism per tech stack: Python repos use pre-commit local hook + `files:` regex; TS/JS use husky / lefthook; Go / Rust use `make test` + CI workflow `step: run: make test`. Common requirement: changing production code triggers tests automatically. |
| Step 0 zero available (all NOT_FOUND or auth failed) | This skill terminates; run `/pr-review-cycle` instead (Claude-only is sufficient) |
| Step 0 detects `KEY_WHITESPACE_PREFIX` | Key has a leading space (e.g. copied from terminal); run `export CODEX_API_KEY="${CODEX_API_KEY# }"` or the corresponding key name to strip leading space, then re-run Step 0 |
| `GEMINI_AUTH: NOT_AUTHED` (agy not configured) | Run `agy` to complete browser OAuth; `onboarding.json`'s `onboardingComplete` will become true; or `export GEMINI_API_KEY=...` |
| Step 0 detects only Codex (no agy) | Enter 2-voice mob (Claude + Codex); normal workflow |
| Step 0 detects only agy (no Codex) | Enter 2-voice mob (Claude + agy); normal workflow |
| Codex detected but auth failed | `codex login`; or `export OPENAI_API_KEY=...` |
| agy detected but auth failed | Run `agy` to complete OAuth; or `export GEMINI_API_KEY=...` |
| agy `@file` error: path not in workspace | This skill already adds `--add-dir "$WT_ROOT"`; if still seeing this error, confirm the prompt's absolute path is under `$WT_ROOT/.pr-review/`; do not use `/tmp` paths |
| agy background bash `>` redirect output not updating target file (unverified) | If this occurs: switch to synchronous bash call (without `run_in_background`) |
| Codex `codex review > file` writes 0 bytes (stderr has full log) | Codex CLI detects stdout is not a tty/pipe and suppresses output when file redirect is used; this skill already uses `set -o pipefail` + `\| tee file > /dev/null` to fix this (`set -o pipefail` makes `$?` reflect failing command exit code in the pipeline; works in bash/zsh) |
| codex review reports `[PROMPT] cannot be used with --base` | `--base` and positional prompt are mutually exclusive; remove the prompt string and keep only `--base` |
| codex review runs against wrong repo | `codex review` does not support the `-C` flag; ensure execution from git repo root (avoid tools like gstack changing CWD, AP3 Sub-class A) |
| A voice fails R1/R2 twice consecutively | Mark as unavailable; do not block; aggregate report notes the reason |
| R2 receives r1-aggregate that is too large for voice to process | Remove raw diff from r1-aggregate; keep only findings; diff was already processed in the r1 prompt |
| 3 consecutive rounds without all voices LGTM | Trigger circuit breaker; report remaining findings to user with three-option decision |
| User chooses to ignore a disputed finding | Add a Known Issues section to the PR description with the reason |
| User raises new concern during human quick pass | Reviewer lead (Claude main) responds immediately; unresolvable → return to Step 6; resolved → wait for user "ship" |
| Want to skip R2 and run only R1 | Not allowed; R2 is the core value of mob review (mutual debate). Switch to `/pr-review-cycle` (Claude-only) if you want to skip it |
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

---

## Relationship to other PR review skills

| Skill | Use case | Reviewer composition |
| --- | --- | --- |
| `/pr-review-cycle` | Small feature / bug fix / refactor; fast merge | Claude pr-review-toolkit 4 subagents in parallel |
| `/pr-cycle-deep` (this skill) | Medium/large PR / high-risk changes / cross-model pressure test | Claude + Codex (required) + agy (optional); R1 independent + R2 debate |

This skill requires ≥1 external reviewer (Codex or agy) to start; with 0, falls back to `/pr-review-cycle`.
agy (Antigravity CLI) is optional — when only Codex is available, runs 2-voice mob; when both are available, runs 3-voice full mob.
