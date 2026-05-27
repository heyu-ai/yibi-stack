---
globs: skills/**
---
# SKILL.md Authoring Guide

## Frontmatter (Required)

```yaml
---
name: <skill-name>        # kebab-case, must match directory name
type: exec                # exec | tool | know
scope: global             # global | project (required; missing causes make install to fail)
description: <one-line description with trigger keywords — keep in Chinese for trigger-word matching>
---
```

### scope Selection Guide

| scope | Criteria |
|-------|----------|
| `global` | Pure methodology, or steps that run in any git repo (knowledge skills, general tools) |
| `project` | Steps require `uv run python -m tasks.*`, `.runtime/*.json` profiles, or repo-specific resources |

**Important**: `make install` only installs skills with `scope: global` by default.
A missing `scope:` field causes install to fail with exit 1 and an error message; it must be added.

If a skill's implementation lives in this repo but is semantically useful cross-project
(e.g. mycelium, local-port-manager), resolve the skill_repo path at the start of
the execution steps and set scope to `global`:

```bash
if ! SKILL_REPO=$(python3 -c 'import json,pathlib; print(json.loads((pathlib.Path.home()/".agents"/"config.json").read_text()).get("skill_repo") or "")'); then echo '[FAIL] 讀取 ~/.agents/config.json 失敗' >&2; exit 1; fi
if [ -z "$SKILL_REPO" ]; then echo '[FAIL] skill_repo 未設定，請在 yibi-stack 目錄執行 make install' >&2; exit 1; fi
if [ ! -d "$SKILL_REPO" ]; then echo "[FAIL] skill_repo 路徑不存在或非目錄：$SKILL_REPO" >&2; exit 1; fi
cd "$SKILL_REPO"
```

**Note (error handling form)**: `cmd || { echo '[FAIL]' >&2; exit 1; }` contains a `'` quote
inside `{}`, triggering the "brace with quote character" confirmation dialog.
Always use `if ! cmd; then echo '[FAIL]' >&2; exit 1; fi` instead (the canonical form above
already uses this).

**Note**: do not use `$(jq -r '.skill_repo' …)` (single-quote filter) or
`$(jq -r .skill_repo …)` (unquoted filter).
The first triggers the AP1 class D hook (leading-dot token inside filter); the second passes
the local hook but the Claude Code built-in parser treats the leading-dot token as an
unparseable string node and pops a confirmation dialog at runtime.

The `python3 -c` single-line form is the only one that passes both sides, but the expression
after `-c` must be wrapped in **single quotes** (use double quotes inside Python) — the
double-quote form `$(python3 -c "...")` is an outer-`$()` → inner-`"..."` reverse-nested
structure that violates rule 13 Quoting Rule 4 and triggers `Unhandled node type: string`.

## Frontmatter — `effort` (Optional, added 2026-05)

Claude Code v2.1.133+ supports specifying effort in skill / slash command frontmatter,
**overriding the caller's model effort**:

```yaml
---
name: <skill-name>
type: exec
scope: global
effort: medium     # optional; low | medium | high
description: ...
---
```

### When to Use `effort` Frontmatter

| Scenario | Recommendation |
|----------|---------------|
| Skill is a "heavy batch" (large downloads, long scans, deep spec expansion) | Pin `effort: medium` or `high` to avoid accidental triggering in a low-effort session |
| Skill is a "quick summary" type | Pin `effort: low` to save tokens |
| Skill behaves similarly across effort levels | Leave unset; follow the caller |

### Relationship to the `${CLAUDE_EFFORT}` Block in SKILL.md Body

Frontmatter `effort` is the **override** final value for the caller's effort;
the `${CLAUDE_EFFORT}` table in the SKILL.md body defines **the execution strategy at that effort level**.
The two work together:

- No frontmatter `effort` + body has `${CLAUDE_EFFORT}` table → dynamically routes based on caller
- Frontmatter `effort: medium` + body has `${CLAUDE_EFFORT}` table → always takes the medium row

### Runtime Gotchas for `${CLAUDE_EFFORT}`

- **`CLAUDE_EFFORT=normal` is the hook default**: hooks use `${CLAUDE_EFFORT:-normal}`;
  a SKILL.md effort table's fallback note must cover both unset AND `normal`
  (both default to full execution — "not-low" behavior, equivalent to `medium`/`high`).
  CC 2.1.133+ makes `$CLAUDE_EFFORT` a real env var in Bash tool / hook scripts
  (read directly; `:-normal` is for pre-2.1.133 compat).
- **Effort fallback is risk judgment, not convention**: general tools default to `medium`;
  spec-expansion / deep-review tools may pin `high`
  because missing spec coverage costs more than doing extra work.
- **`${CLAUDE_EFFORT}` does not expand in static SKILL.md**: the agent reads it
  as a literal string. To get the actual value, use `echo "${CLAUDE_EFFORT:-normal}"`.
  Hook scripts (bash, CC 2.1.133+) can read `$CLAUDE_EFFORT` directly as an env var
  — no `echo` subprocess needed.

## Exec Skill Standard 4-Step Template

```markdown
## Steps

### Step 1 — Environment Check
Confirm you are in the git repo root and required tools are available:
- `uv --version` OK
- Confirm `.env` exists

### Step 2 — Config Check
Confirm `.runtime/<config>.json` exists; ask the user to confirm key parameters:
- Profile: {{profile_name}}

### Step 3 — Execute
uv run python -m tasks.<module> <command> --profile {{profile_name}}

### Step 4 — Report Results
Report: success count, failed items, output path.
```

## `{{value}}` Placeholder

Parameters that require user confirmation use double braces: `{{profile_name}}`, `{{date}}`.

## FAQ Table

Append a FAQ at the end of each exec skill:

```markdown
## FAQ

| Issue | Fix |
|-------|-----|
| Config file not found | Run the `setup` subcommand to create the default config |
| API 403 error | Check whether the token in `.env` has expired |
```

## Knowledge Skill (type: know)

- Contains only methodology guidance; no Python execution steps
- May have multiple sections (e.g. Core Loop, Anti-patterns)
- Put rich trigger keywords in the `description` field

## Update the Index

After creating or modifying a skill, update the index table in `skills/README.md`.

`skills/README.md` has two tables under the "Global Skills" section:
"Executable/Tool (exec/tool)" and "Knowledge (know)".
`scope: project` exec skills belong to a third "Repo-Specific" table and are out of scope here.
**Classification is based on the `type` field in the SKILL.md frontmatter, not how the skill feels**:

| frontmatter `type` | Target table |
|--------------------|-------------|
| `exec` or `tool` | Executable/Tool |
| `know` | Knowledge (methodology) |

Common mistake: a `type: know` skill is placed in the tool table because it "feels executable"
(e.g. `bump-version`).
Before editing the README, confirm the type with (run from repo root):

```bash
grep -m1 '^type:' skills/<name>/SKILL.md
```

## Reference Template

`skills/_template/SKILL.md.tpl` is the canonical format reference.

## Decision Table and Prose Consistency

A decision table (mode table) must be self-contained: it cannot rely on prose outside the table
to describe exceptional behavior.
When an agent reads a SKILL.md, it executes by table row first; explanatory paragraphs outside
the table are easily skipped.

Correct approach:

- Add a guard row to the table (e.g. "any tool BINARY_OK+NOT_AUTHED → run stop flow first,
  do not enter count calculation")
- Or explicitly annotate applicable conditions in the action column of the matching row
  (e.g. "0 (all NOT_FOUND, no auth failures)")

Anti-pattern: prose says "stop when state X is detected", but the `count=0` row in the table
says "redirect terminate" — the agent follows the table and the prose intent is completely overridden.

## FAQ Fix Command Format

Fix commands in FAQ tables must meet three requirements:

1. **Use real variable names**: do not use placeholder literals like `KEY`;
   write actual names like `CODEX_API_KEY` / `GEMINI_API_KEY`
2. **Shell-hygiene-safe syntax**: use parameter expansion `"${VAR# }"` to strip leading spaces;
   do not use `$(echo $VAR)` subshell (does not trim in zsh; also triggers rule 13 quoting hygiene hook)
3. **Cross-shell compatible**: commands must work correctly in both zsh (macOS default) and bash

## Table Description Column — Single Responsibility

The description column of a Markdown table should contain only **functional description**;
do not repeat information from other columns (e.g. the Install column).

Common mistake: appending the install path in the description column
(e.g. `— no package.json, installed as global skill`).
The Install column already carries the install command; duplicating it in the description creates
a double-maintenance burden when the install method changes, and is inconsistent with other rows.

## Hook Descriptions Must Be Verified Against the Actual Script (PR #303 lesson)

When describing hook behavior in CLAUDE.md or SKILL.md, **always Read the hook script itself**;
do not write from memory or stale documentation.

Common mistake: description says "runs ruff format on .py files after Write/Edit" — but the
actual script only covers `backend/**/*.py`, and also runs `ruff check` (lint),
`tsc --noEmit` (frontend), and `terraform fmt -check` (infra).

Correct approach:

1. Use the Read tool to open `.claude/hooks/<hook-name>.sh` (or the actual script path)
2. Check the path guard (e.g. `*backend*`, `*frontend*`) to confirm which file types are actually affected
3. List all tool invocations line by line, scoped to actual coverage

```markdown
<!-- Wrong: written from memory / guessing -->
**Hook side-effects** -- automatically runs `ruff format` on `.py` files

<!-- Correct: verified against script, full coverage listed -->
**Hook side-effects** -- `post-edit-check.sh` runs automatically after Write/Edit/MultiEdit:
- `backend/**/*.py`: `ruff format` + `ruff check` (per-file)
- `frontend/**/*.{ts,tsx}`: `tsc --noEmit` (project-wide type check)
- `*.tf`: `terraform fmt -check`
```

The Claude voice in mob review found the mismatch after reading the script; Gemini R1 reported
"accurate (low confidence)" and only agreed on the fix after seeing Claude's findings in R2.
Description accuracy cannot rely on reviewer cross-checking — verify at authoring time.

## Cross-doc Cite Must Paste the Original Quote, Not a Summary from Memory (PR #415 lesson)

When a rule / doc / SKILL.md cites "another authoritative source" (another rule file, another
repo's document, an official API spec), **paste the original quote or an exact section reference;
do not paraphrase from memory**.
Memory paraphrases silently introduce errors in direction / active-passive voice / scope, and
first-round reviewers typically miss them because they only verify that the cited source exists,
not that the cited content supports the argument.

Typical failure pattern:

- `13-bash-anti-patterns.md` "exec wrapper penetrates deny rule (2026-05)" section
  Original: "Claude Code deny rules now see through `env` / `sudo` / `watch` ...
  do not assume a wrapper bypasses a deny rule" — meaning **deny rule is stronger, sees through wrapper**
- A new rule's first draft quoted this as: "the PATH= env-wrapper pattern **can penetrate deny rules**"
  — meaning flipped to **wrapper is stronger, bypasses deny rule**; active/passive reversed,
  **argument is the opposite of the source**
- First-round code-reviewer confirmed "source file exists + section name matches" and passed;
  second-round comment-analyzer caught the reversal by comparing against the original quote

How to avoid:

```markdown
<!-- Wrong: paraphrased from memory; active/passive easily inverted -->
Per yibi-stack 13-bash-anti-patterns.md "exec wrapper penetrates deny rule" section,
PATH= can also penetrate deny rules.

<!-- Correct: paste original quote; direction is self-evident -->
yibi-stack `.claude/rules/13-bash-anti-patterns.md` original:
> Claude Code deny rules now see through `env` / `sudo` / `watch` / `ionice` / `setsid`:
> ... do not assume a wrapper bypasses a deny rule.

From the original: **deny rule** blocks **wrapper**; wrapper cannot bypass deny rule.
```

Criteria for when to paste vs. summarize:

| Citation type | Paste or summarize? |
|---------------|---------------------|
| Direction (X attacks Y / Y attacks X; who is active / passive) | **Must paste** original; read direction yourself |
| Condition / scope (do Y when X) | **Must paste** condition original; avoid dropping the premise |
| Conclusion (result is Z) | May summarize, but the "because..." premise paragraph before the conclusion must be pasted |
| Tool / concept introduction | May summarize |

Cross-doc cites must verify **both ends** independently:

1. **Citation target**: file / section actually exists (path correct, not drifted)
2. **Citation content**: original actually supports your argument (direction / condition / scope aligned)

Verifying only the first end lets **dangling references** through
(link is correct but content is inverted).
Reviewer agent prompts should explicitly require "verify both ends of every cross-ref";
otherwise a single-source reviewer will miss inversion / mis-paraphrase errors.

Relationship to "Hook Descriptions Must Be Verified Against the Actual Script": both belong to
the cross-doc / cross-artifact verification discipline — hook docs must match the script,
rule cites must match the source, rule-to-spec relationships must match the source spec.
Verify at authoring time; do not assume a reviewer will catch it.

**Comment-analyzer catches direction errors that code-reviewer misses**: in PR #107, an Output
Filter section cited Red Flag 5 as the rationale for avoiding output filter pipelines. The real
reason is that pipeline sources vary at runtime (the source command is not fixed), making any
allow-list pattern necessarily too broad. Code-reviewer passed the citation (source file exists,
section name plausible); comment-analyzer caught the direction error by reading what Red Flag 5
actually says. **Both ends of every cross-ref must be independently verified** — target path AND
cited content alignment. Checking only the path is insufficient.

## Cross-Repo Citation: Doc Body Must Be Self-Contained; Lineage Goes in Commit Message

When codifying a lesson / incident from another repo into a doc / skill / rule, **do not embed
cross-repo source pointers like "Source: `<other-repo>` PR #`<N>` retro" in the doc body**.
Downstream readers may not have access to the source repo; the pointer is a dead link.
Even with access, switching repos and digging through retros costs ~10x more than reading the
doc itself.

Correct approach:

1. **Doc body**: a reproducible summary of the original incident (self-contained, with enough
   context that the reader can understand the lesson without leaving this repo).
2. **Commit message**: detailed lineage ("derived from `<repo>` PR #`<N>` retro" + handover ID + date).
3. **PR description**: same as commit message, plus motivation for why this lesson was ported cross-repo.

Evidence: yibi-stack PR #36 (pr-test-analyzer FAQ) — first version appended
"Source: openab_workspace PR #73 retro." at the end of the FAQ row.
code-reviewer NIT-1 and comment-analyzer Important #2 both flagged it: yibi-stack readers
have no access to openab_workspace, so the pointer is a dead link.
The fix removed the source pointer from the doc body, moved it to commit message + PR description,
and rewrote the FAQ row to be fully self-contained using generic helper names
(no longer tied to openab_workspace's `require_kubectl_context`).

Relationship to "Cross-doc Cite" (above): both are cross-doc writing hygiene, but on different axes —
Cross-doc Cite requires **pasting the original when citing** to avoid direction errors;
this section requires **the doc body to remain self-contained after citing** to avoid dead links.
In practice, follow both: first paste the original to verify direction, then naturally integrate
the verified content into this repo's narrative — leave no cross-repo pointers.

## Retro / Lesson-Routing Skills Must Name a Concrete Destination for Next Steps

Any skill that produces follow-up actions from retro / review results
(`/pr-retro`, various `*-cycle`, `*-review` skills) must not write vague language like
"consider", "maybe", "decide later" in the "next steps" section —
**verb is vague + destination is absent**.

Evidence: after yibi-stack PR #36 retro (handover `c88c0e9e`), the agent used a 4-option
AskUserQuestion (A/B/C/D) to route three testing-discipline lessons to concrete destinations
(each option mapped to an actual rule file + section name);
the user chose A and the lesson landed within one round (this PR is that landing).
Counter-example: if the follow-up only says "consider writing the lesson into documentation",
the user needs another "where?" round trip — retro landing rate drops by an order of magnitude.

Correct approach (at skill design time):

```markdown
<!-- Wrong: vague verb + no destination -->
- [ ] Consider writing the lesson into documentation

<!-- Correct: explicit destination + verb -->
- [ ] Write to `.claude/rules/15-irreversible-operations.md` Category 3 Recovery section (git workflow recovery)
- [ ] Write to `~/.claude/CLAUDE.md` cross-project personal preferences section
- [ ] Write to `<repo>/CLAUDE.md` Gotchas section (repo-specific)
- [ ] Do not document; mycelium handover only (one-off / non-recurring lesson)
```

Each option's "destination file + section" should already have been computed by the skill itself
(class maps to routing table), so the user sees actionable paths in AskUserQuestion,
not abstract suggestions.

Source practice: `/pr-retro` Step 5 Lesson Classifier (pr-retrospective SKILL.md) uses this pattern.

## Inserting a New Blockquote After an Existing One Requires Removing the Blank Line (MD028)

When inserting a new blockquote after an existing blockquote block, if there is a blank line
between them, markdownlint triggers **MD028/no-blanks-blockquote** (the blank line is treated
as "a blank line inside the same blockquote").

```markdown
<!-- Wrong: blank line between two blockquotes -->
> Existing text.

> **New execution note**: ...

<!-- Correct: remove blank line; merge into a single continuous blockquote -->
> Existing text.
> **New execution note**: ...
```

Common pitfall: inserting an "execution note" blockquote after a security warning blockquote.
The original `blockquote → blank line → code block` is valid, but changing it to
`blockquote → blank line → blockquote` violates MD028.
This pattern has recurred multiple times in this repo (PR #5, #24, #70).

**Quick validation** (run before committing to avoid CI roundtrips):

```bash
uv run pre-commit run markdownlint-cli2 --files plugins/<plugin>/skills/<name>/SKILL.md
```

## Scripts with Built-in stderr Logging Need a No-Capture Blockquote Hint

The background session harness automatically appends `> $CLAUDE_JOB_DIR/<name>.log 2>&1` to
Bash commands for output isolation and cross-compaction persistence.
For scripts that **already write stderr to an internal log**, this extra capture is redundant
and triggers a `~/.claude/` sensitive file permission dialog
(`$CLAUDE_JOB_DIR` contains a per-session UUID that cannot be permanently allow-listed).

**Fix**: add a blockquote execution note before the bash code block to explicitly tell the agent
not to append external capture:

```markdown
> **Execution note**: the script writes stderr to `$REVIEW_DIR/<name>.log`; stdout outputs
> only "<completion message>". **Run directly — do not append `> $CLAUDE_JOB_DIR/foo.log 2>&1`** —
> Read `$REVIEW_DIR/<name>.log` on failure to see the full error.

\`\`\`bash
bash ~/.agents/skills/<skill>/scripts/<name>.sh
\`\`\`
```

**Applies when** the script meets all three conditions:

1. stderr is redirected to a fixed log file path (not stdout)
2. stdout outputs only a single "done" message (no diagnostic output the agent needs to read)
3. Runs in a background session flow (harness automatically appends log capture)

## Spec and SKILL.md behavioral guards must stay in sync

Any guard or exception in SKILL.md — a zero-score condition, a threshold constraint,
a tie-breaking rule — must be reflected in the corresponding spec.md decision table.

If the guard exists only in SKILL.md, the spec cannot be used to cross-check agent
behavior during review; if it exists only in spec.md, the agent never sees it.

**Pattern**: whenever you add a guard to SKILL.md, immediately update spec.md's decision
table (and vice versa). The two documents describe the same contract from different angles:
SKILL.md is the agent's execution interface; spec.md is the verifiable source of truth.

Example from harness-eval D5 (PR #83): in one commit the EG-* sub-item in SKILL.md was
tightened to require "at least 2 distinct EG categories" but spec.md's decision table was
not updated to match. Mob review round 4 caught the divergence and synced spec.md to reflect
the constraint.

## MCP Call Failure Gates: Concrete Examples

General rule in `~/.claude/CLAUDE.md`: "Each external call (MCP tool, bash CLI) must have an
explicit `[FAIL]` stop condition with a clear error message."
The following shows the common missing-gate pattern in SKILL.md and the correct form:

```markdown
<!-- Wrong: no failure gate after MCP call; tool error silently continues -->
Call `mcp__claude_ai_Atlassian__getTransitionsForJiraIssue`
(`issueId`: `{{jira_issue_key}}`) to get the transition list.

Pick the option closest to "done"...

<!-- Correct: add failure condition immediately after each MCP call -->
Call `mcp__claude_ai_Atlassian__getTransitionsForJiraIssue`
(`issueId`: `{{jira_issue_key}}`) to get the transition list.
If the call fails, stop and report the error to the user.

Pick the option closest to "done"...
```

**Scope**: all MCP tool calls, including read-only queries (`get*`, `list*`, `search*`) —
a query failure does not mean "no results"; it may be an auth error or connection issue.
Without a gate, the agent continues with empty results and downstream steps silently drift.

**Parallel call failure gates**: when multiple MCP calls are dispatched simultaneously,
each call's failure must be reported independently:

```markdown
<!-- Wrong: dispatched in parallel with no per-call failure condition stated -->
Send in parallel:
- `mcp__...__transitionJiraIssue`
- `mcp__...__addCommentToJiraIssue`

<!-- Correct: explicitly state that either failure must be reported -->
Send in parallel (no dependency); **either failure must be reported
and must not be silently ignored**:
- `mcp__...__transitionJiraIssue`
- `mcp__...__addCommentToJiraIssue`
```

## MD013 Line-Length Validation for Translation PRs

Chinese prose translated to English consistently produces longer lines
(~30 CJK characters → 60+ English characters), frequently exceeding the MD013 200-character
limit. Translation PRs tend to accumulate many MD013 violations that are invisible until CI runs.

**Run this after translating, before committing**:

```bash
uv run pre-commit run markdownlint-cli2 --files plugins/<plugin>/skills/<name>/SKILL.md
```

Preferred line-break positions (in priority order):

1. After a period (`.`)
2. After a semicolon (`;`) or dash (`—` / `--`)
3. Before a conjunction (`and`, `or`, `when`, `if`)
4. Before an opening parenthesis

MD013 exempts table rows and code block lines (`tables: false`, `code_blocks: false`) —
only pure prose lines need to stay within 200 characters.

## Dual-Source Document Ownership (PR #112 lesson)

When two files both need to reflect the same methodology content
(e.g. a `SKILL.md` human entry and an `agent.md` programmatic entry both referencing the same technique list),
only **one file is the owner** that defines the canonical format and column names.
The other file must be explicitly labelled as a compressed summary — not a copy to sync.

**Wrong pattern**: both files declare themselves the source of truth and instruct maintainers to "sync the inline copy."
A maintainer following this instruction will overwrite the correct format with the wrong one.

**Correct pattern**:
- Owner file: defines canonical column headers, format, and technique names
- Summary file: explicitly states "this is a condensed summary optimized for in-context use;
  when technique semantics change, re-summarize this section — do NOT copy-paste from the owner file"

**Real incident (PR #112)**: `methodology.md` defined Coverage Analysis with "Expected Coverage Item" as the first column;
`qa-test-designer.md` (the file that actually produced output) correctly used "Scenario Slug."
Both files claimed to be the source of truth. A mob review Critical finding caught the divergence.
Fix: `methodology.md` was updated to use "Scenario Slug"; the sync instruction was changed to "re-summarize."

## Task Subagent Failure Gates — Three Required Paths (PR #112 lesson)

When a SKILL.md dispatches a Task subagent, the failure gate must cover all three paths.
A gate that only covers path (a) silently produces garbage output on paths (b) and (c).

| Path | Example | Required gate |
|------|---------|---------------|
| (a) Subagent not available | plugin not installed | `If sdd:subagent not available: [FAIL] Stop.` |
| (b) Subagent ran but returned `[FAIL]` | all capabilities were `[BLOCKED]` | check output prefix before proceeding to next step |
| (c) Platform error | timeout, context-limit exceeded | catch Task tool failure itself |

**Template** (append after Task tool dispatch block):

```markdown
After receiving output from `sdd:subagent-name`:
- If the Task tool call itself failed (error / empty output):
  `[FAIL] sdd:subagent-name Task failed. Confirm plugin version and retry.`
- If output starts with `[FAIL]`:
  Stop. Surface the exact message to the user. Do not proceed to the next step.
```

Also add a pre-dispatch guard for the "all inputs filtered" case:

```markdown
If all inputs are `[BLOCKED]` (nothing to pass to the subagent):
`[WARN] All capabilities [BLOCKED] — skipping subagent dispatch.`
```

**Real incident (PR #112)**: spectra-amplifier Step 2a only had path (a).
When all capabilities were `[BLOCKED]`, the subagent returned `[FAIL]`,
Step 2b executed unconditionally, and a garbage `testplan.md` was written with no user-visible error.
