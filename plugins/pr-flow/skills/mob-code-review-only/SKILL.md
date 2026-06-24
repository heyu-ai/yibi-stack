---
name: mob-code-review-only
type: know
scope: global
description: >
  Multi-frontier-model mob review of someone ELSE's PR — review-only, never modifies their code.
  自動偵測 codex / agy，≥1 家即啟動 R1 獨立 + R2 交叉 debate + aggregate，產出彙整 review 報告
  並（經確認後）貼回 PR 作為建議留言。與 `/pr-cycle-deep` 共用同一套 mob review 引擎，差別在於：
  目標是**別人的 PR**、只給修改建議、**不**動手改 code、**不** re-review loop、**不** merge / archive。
  適用：review 同事 / 外部貢獻者的 PR、code review approval gate、跨家 LLM 壓力測試他人改動。
  偵測不到任何外部模型時提示退回 `/pr-review-cycle`（Claude-only review，亦不修改）。
  觸發情境：「review 別人的 PR」「幫我 review 這個 PR 給建議」「mob review only」「不要幫他改只給意見」
  「multi-model review someone else's PR」「code review approval」「review-only」「給 PR 留言建議」
---

# Mob Code Review — Only (Review someone else's PR, suggestions only)

Multi-frontier-model **mob review of a PR you do NOT own**. Produces an aggregated, cross-model
review report and (after your confirmation) posts it back to the PR as constructive feedback for
the author. **It never modifies the author's code.**

This skill **reuses the exact mob review engine of `/pr-cycle-deep`** (reviewer detection + R1
independent review + R2 cross-debate + aggregation). `/pr-cycle-deep` is the **engine owner**;
this skill is a thin wrapper that changes only three things:

| Delta | `/pr-cycle-deep` | `mob-code-review-only` (this skill) |
| --- | --- | --- |
| **Target** | Your own PR / current branch | **Someone else's PR** (fetched via `gh pr checkout`) |
| **Action on findings** | Fix → commit → re-review until all voices LGTM | **Deliver as suggestions only** — never edit, commit, or push |
| **Lifecycle tail** | Human pass → CI → merge → spectra archive → Jira sync | **Stops after delivering feedback** — no merge, no archive |

## When to use

- You are reviewing a **teammate's / external contributor's PR** and want broad, cross-model coverage.
- You want a defensible **approval gate**: multiple LLM families independently flag the same issues.
- You explicitly **must not touch the author's branch** — only leave review comments.

## When NOT to use

- **Reviewing AND fixing your own PR** → use `/pr-cycle-deep` (full lifecycle with fix loop).
- **Small PR, Claude-only review is enough** → use `/pr-review-cycle` (also review-only, no external models).
- **One quick external second opinion** → use `/agy` or `/codex` (single reviewer, no mob).
- **No external model installed** → this skill terminates and points you to `/pr-review-cycle`.

## Usage

```text
/mob-code-review-only #<PR number>
/mob-code-review-only <PR URL>
```

A PR number (or URL) is **required** — this skill always reviews an existing PR you specify.

---

## Step 1 — Identify & fetch the target PR

> **Why checkout**: codex (`codex review --base`) and agy (`--add-dir .`) need the PR's working
> tree for surrounding-code context, not just the diff. `gh pr checkout` is the standard way to
> review a PR locally and handles fork-based PRs automatically.
>
> **Working-tree safety**: `gh pr checkout` switches your current branch. Run this skill in a
> dedicated worktree (or confirm your working tree is clean first) so you don't disrupt in-progress
> work. A background/isolated session is already safe.

### 1a — Pre-flight: confirm clean working tree

```bash
git status --short
```

Non-empty output → there are uncommitted changes. **Stop** and tell the user: commit/stash first,
or re-run this skill inside a fresh worktree. Do not `gh pr checkout` over a dirty tree.

### 1b — Resolve PR metadata

```bash
gh pr view "{{pr_number}}" --json number,title,headRefName,baseRefName,author,isDraft
```

If the command exits non-zero (PR not found / auth / network) → `[FAIL]` and stop; show the error.
Note the base branch as `{{base_branch}}` (the `baseRefName` field) and the author as `{{author}}`.

### 1c — Checkout the PR

```bash
gh pr checkout "{{pr_number}}"
```

Non-zero exit → `[FAIL]` and stop (e.g. local branch name collision; show the error).

---

## Step 2 — Reviewer detection

Run **`/pr-cycle-deep` Step 0** exactly as written there (Step 0a cache reuse + auth re-verify, or
Step 0b full detection + `~/.claude/mob-detection-cache` write). The detection logic, the
`BINARY_OK + NOT_AUTHED` stop behavior, and the mode table are **owned by `/pr-cycle-deep`** — do
not re-derive them here.

Outcome mapping for this skill:

| Available external reviewers | Action |
| ---: | --- |
| 0 (all NOT_FOUND, no auth failures) | **Terminate** — tell the user to run `/pr-review-cycle` (Claude-only review, also review-only) |
| **1** (Codex or agy) | **2-voice mob** (Claude + 1 external) |
| **2** (Codex + agy) | **3-voice full mob** |

Any `BINARY_OK + NOT_AUTHED` / `KEY_WHITESPACE_PREFIX` → do **not** silently drop the voice; show
the fix command and wait for re-auth, then re-run detection (identical to `/pr-cycle-deep`).

Report the detected mode and wait for the user to confirm before continuing.

---

## Step 3 — Run the mob review engine (produce the report)

Execute **`/pr-cycle-deep` Steps 1.5 → 5 exactly as written**, using the **same scripts, the same
R1/R2 prompts, the same sanity checks, and the same aggregation severity table**. The base branch
for `setup-review-dir.sh` is the PR's `{{base_branch}}` from Step 1b; use `origin/{{base_branch}}`
if the local base ref is stale or absent:

| Engine step (owned by `/pr-cycle-deep`) | What runs |
| --- | --- |
| **Step 1.5** Parallel pre-review check | 3 Task agents in one message: `gh pr diff` / `gh pr checks` / `amplifier-verify.py --pr {{pr_number}}` |
| **Step 2** Code review | `/code-review` (report-only) for defect detection |
| **Step 3** Round 1 | `setup-review-dir.sh {{base_branch}}` → each voice reviews independently → `<voice>-r1.md` |
| **Step 4** Round 2 | Build `r1-aggregate.md` → each voice cross-debates → `<voice>-r2.md` |
| **Step 5** Aggregation | Lead synthesizes `final.md` per the RFC 2119 severity table |

The script invocations are the same installed paths (shared with `/pr-cycle-deep`):

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/setup-review-dir.sh {{base_branch}}
```

then per available voice: `codex-r1-stage1.sh` / `codex-r1-stage2.sh` (Codex), `agy-r1-stage1.sh` /
`agy-r1-stage2.sh` (agy), the 4 `pr-review-toolkit` subagents (Claude), and for R2
`codex-r2.sh` / `agy-r2.sh`. Read each voice's JSON → render compact `<voice>-r{1,2}.md`. Honour the
JSON-invalid fallbacks and the 2-consecutive-failures "mark voice unavailable, do not block" rule
exactly as `/pr-cycle-deep` specifies.

> **Single-voice [Critical] → empirically verify BEFORE writing it into the report.** This matters
> *more* here than in `/pr-cycle-deep`: a wrong Critical posted to someone else's PR is a public
> false accusation. Construct a minimal repro and run it; confirmed → keep, refuted → drop with the
> evidence noted, can't-test → label "unverified — needs author input" in the report. (Same rule as
> `/pr-cycle-deep` Step 5 single-voice handling.)

**Review-only reframing — the only behavioral change to the engine:**

- The `final.md` severity grades (Consensus Critical / Important / Actionable NIT / Disputed) are
  **the author's to-do list, not yours.** Phrase every item as an actionable *suggestion* with a
  concrete fix the author can apply — never as a change you will make.
- **Do NOT** run `/pr-cycle-deep` Step 6 (Fix), Step 7 (re-review loop), Step 8 (human pass to ship),
  Step 9 (CI watch), Step 10 (merge), or Step 11 (archive / Jira). The engine stops at `final.md`.
- There is **no convergence loop**: this is a single R1 + R2 + aggregate pass. You are not waiting
  for LGTM because you are not fixing anything.

Report the `final.md` summary to the user. For any **Disputed** item, surface both sides and let the
user decide whether it belongs in the feedback — do not unilaterally assert a disputed finding on
the author's PR.

---

## Step 4 — Deliver the feedback

Posting a comment to someone else's PR is an **outward-facing action** — get explicit user
confirmation before posting (the user may want to edit tone or drop disputed items first).

### 4a — Show the report and confirm

Show the user the `final.md` content (or its path) and ask:

```text
Mob review complete ({{N}}/3 voices). Report: <REVIEW_DIR>/final.md
Post this as a review comment on PR #{{pr_number}} (by {{author}})?
  [Post as one summary comment / Post as inline comments / Don't post — I'll handle it]
```

### 4b — Post (after confirmation)

**Option A — single summary comment** (default; recompute `REVIEW_DIR` in the same block, since each
Bash call is a fresh shell):

```bash
WT_ROOT=$(git rev-parse --show-toplevel)
REVIEW_DIR="$WT_ROOT/.pr-review"
if [ ! -f "$REVIEW_DIR/final.md" ]; then
  echo "[WARN] final.md missing -- complete Step 3 first, then re-run this block" >&2
else
  gh pr comment "{{pr_number}}" --body-file "$REVIEW_DIR/final.md"
fi
```

`gh pr comment` exit codes: **exit 0** → report the comment URL to the user; **non-zero** (auth /
network / PR not found) → `[WARN] 無法貼 review 留言到 PR`, show the manual command, and report the
report path so the user can post it themselves.

> First-time `gh pr comment` use: if prompted every run, add `Bash(gh pr comment:*)` to
> `settings.local.json` (rule 16 safe form — verb locked at prefix).

**Option B — inline comments**: re-run Step 2's `/code-review --comment` to post defect findings as
GitHub inline comments, then post `final.md` as the summary comment (Option A) for the mob consensus.

**Option C — don't post**: report the `final.md` path to the user and stop.

### 4c — Wrap up

Report to the user: voices active, headline counts (Consensus Critical / Important / NIT / Disputed),
the verdict per voice, and the comment URL (if posted). **Do not** offer to fix, merge, or archive —
those belong to the PR author.

---

## What this skill does NOT do (boundary)

| Not done | Why | Who does it |
| --- | --- | --- |
| Edit / commit / push code | This is review of someone else's PR | The PR author |
| Re-review loop until LGTM | No fixes means nothing to converge on | — (single pass) |
| `gh pr merge` | Not your PR to merge | The PR author / maintainer |
| `spectra archive` / Jira sync | Lifecycle wrap-up belongs to the owner | The PR author |

If, after reviewing, **you decide to take over and fix the PR** (e.g. it becomes your branch),
switch to `/pr-cycle-deep` — that skill owns the fix → re-review → merge lifecycle.

---

## FAQ

| Issue | How to handle |
| --- | --- |
| Engine scripts missing (`~/.agents/skills/pr-cycle-deep/scripts/...` not found) | `/pr-cycle-deep` is not installed. Run `make install` in the yibi-stack repo, or `claude plugin install pr-flow@yibi-stack`. Verify: `ls ~/.agents/skills/pr-cycle-deep/scripts/setup-review-dir.sh` returns the path |
| `git status --short` shows uncommitted changes | Do not `gh pr checkout` over a dirty tree; commit/stash, or re-run inside a fresh worktree |
| `gh pr checkout` fails with local branch name collision | The PR's head branch name already exists locally; `gh pr checkout {{pr_number}} -b mob-review-{{pr_number}}` to use an alternate local name |
| `setup-review-dir.sh` reports base ref invalid | Use `origin/{{base_branch}}` instead of the bare name (the local base ref may be stale or absent after checkout) |
| 0 external reviewers detected | This skill terminates; run `/pr-review-cycle` (Claude-only review, also review-only) |
| A voice flags a single Critical the others missed | Empirically verify with a minimal repro **before** writing it into the report — a wrong Critical on someone else's PR is a public false accusation (Step 3) |
| `gh pr comment` fails (auth / network) | `[WARN]`; show the manual command and report the `final.md` path so the user can post it themselves; do not block |
| User wants me to also fix the issues | Out of scope by design — this skill is review-only. Switch to `/pr-cycle-deep` if the PR becomes yours to fix |
| All other engine issues (JSON extract fails, agy went agentic, voice failed twice, etc.) | Handled identically to `/pr-cycle-deep` — see its Troubleshooting table (engine owner) |

---

## Relationship to other PR review skills

| Skill | Target | Fixes code? | Reviewers |
| --- | --- | --- | --- |
| `/pr-review-cycle` | Your own PR | Yes (then merge) | Claude pr-review-toolkit 4 subagents |
| `/pr-cycle-fast` | Your own PR | Yes (then merge) | Claude (state machine, 1 reviewer) |
| `/pr-cycle-deep` | Your own PR | Yes (then merge) | Claude + Codex + agy (mob, R1+R2) |
| **`/mob-code-review-only`** (this skill) | **Someone else's PR** | **No — suggestions only** | Claude + Codex + agy (mob, R1+R2) |
| `/agy`, `/codex` | Any PR / diff | No | Single external model |

This skill requires ≥1 external reviewer (Codex or agy) to start; with 0, it points you to
`/pr-review-cycle`. agy is optional — Codex-only runs a 2-voice mob; both available runs a 3-voice
full mob.
