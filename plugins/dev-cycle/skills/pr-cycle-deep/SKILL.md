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
/pr-cycle-deep #<PR number> --resume   ← continue from .pr-review/state.md (see Step 5 Checkpoint)
```

`--resume`: run Step 0a, Read `state.md` + `final.md`, re-check live PR state (Step 6 recheck
table), then jump to its `next:` step. `state.md` missing, naming another PR, or its `head:` ≠ the
live `gh pr view --json headRefOid` (unreviewed commits) → `[FAIL]`; rerun without `--resume`.

---

## Step 0 — Reviewer Detection (determine workflow mode)

### Step 0a — Read detection cache & auto-verify auth

Use the Read tool to try reading `~/.claude/mob-detection-cache`:

- **File exists** (warm path): **do not ask whether to use the cache** — the default is silent
  reuse. Trust the cached binary detection + mode, but **re-verify the auth tokens** for the
  cached-available voices (auth can go stale even when the binary is unchanged). Run the detection
  script in auth-only mode and read only the lines for the voices the cache marks available
  (`CODEX_AUTH:` when `CODEX_OK=1`, `GEMINI_AUTH:` when `GEMINI_OK=1`):

  ```bash
  python3 ~/.agents/skills/pr-cycle-deep/scripts/detect_voices.py --auth-only
  ```

  Then branch on the result:
  - **All cached-available voices still auth OK** → report one line and **go directly to Step 1**:

    ```text
    [Cache] Reusing detection ({{DATE}}): Mode={{MODE}} — auth re-verified OK, proceeding.
    ```

  - **Any cached-available voice now `NOT_AUTHED` / `KEY_WHITESPACE_PREFIX`** → that token expired
    or broke. Do **not** proceed and do **not** silently drop the voice. Show the fix command for
    that voice (see the Step 0b report block / Troubleshooting), wait for the user to
    re-authenticate, then re-run Step 0 from **0b** (full re-detect + refresh cache).
  - **Non-zero exit, or not exactly 2 lines** → `[FAIL]`, stop; see **Script failure** in Step 0b.
- **File does not exist** (Read tool returns error): run Step 0b directly.

> **Why re-verify instead of asking**: valid auth is the common case, so silent reuse is the
> default; only a real auth failure stops the flow. A present-but-expired token that slips the
> static check is caught at use-time by R1 fail-loud (`agy_validate.py` / codex error), which marks
> that voice unavailable and proceeds with the rest — no block. The warm path re-verifies auth only,
> not `GEMINI_ALLOW_LIST` (a stale allow-list only adds a per-call prompt). Force a full re-detect
> by deleting `~/.claude/mob-detection-cache`.

### Step 0b — Run detection

One call runs the whole detection. **Run the script as written — do not re-type its checks as
inline bash**: the detection used to live here as five bash blocks, and agents rewrote them on
every run (untested, and a multi-line block cannot be matched by any prefix allow-list, so every
run prompted):

```bash
python3 ~/.agents/skills/pr-cycle-deep/scripts/detect_voices.py
```

It prints five lines, always in this order, and exits 0 whatever the detection result:

| Line | Values | Meaning |
|------|--------|---------|
| `CODEX:` | `BINARY_OK` / `NOT_FOUND` | `codex` on `PATH` |
| `CODEX_AUTH:` | `KEY_SET` / `KEY_WHITESPACE_PREFIX` / `FILE_EXISTS` / `NOT_AUTHED` | `CODEX_API_KEY` or `OPENAI_API_KEY`, else non-empty `~/.codex/auth.json` |
| `GEMINI:` | `BINARY_OK` / `NOT_FOUND` | `agy` on `PATH` (the `GEMINI` prefix is kept for the cache's `GEMINI_OK` key) |
| `GEMINI_AUTH:` | `ONBOARDED` / `KEY_SET` / `KEY_WHITESPACE_PREFIX` / `NOT_AUTHED` | agy `onboarding.json` `onboardingComplete: true`, else `GEMINI_API_KEY` / `GOOGLE_API_KEY` |
| `GEMINI_ALLOW_LIST:` | `OK` / `MISSING` | all 3 agy script paths are allow-listed in `~/.claude/settings.json` |

A `[WARN]` on stderr means `~/.codex/auth.json`, agy `onboarding.json` or `settings.json` could not be checked,
read or parsed, or has the wrong shape; the script treats it as absent — relay the `[WARN]` text to the user.
It never prints a key's value.
**Script failure (Step 0a and 0b)**: any non-zero exit (2 = bad argument, or python could not find the script),
or a line count other than 5 (2 with `--auth-only`), is `[FAIL]` — stop and show stderr verbatim.
stderr containing `can't open file` means the installed skill copy is missing or stale (update the plugin /
re-run `make install` from the main repo). Never fall back to re-typing the checks as inline bash,
and never count a failed run as 0 voices.
Allow-list it once with two exact entries (no wildcard needed):
`Bash(python3 /Users/<you>/.agents/skills/pr-cycle-deep/scripts/detect_voices.py)` and
`Bash(python3 /Users/<you>/.agents/skills/pr-cycle-deep/scripts/detect_voices.py --auth-only)`.

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

**Spec-drift preflight (before drafting, new or existing PR; issue #510).** A spec, proposal or PR
body records intent as of when it was written; a later commit can change that intent (default
provider, dependency, interface), and a contract drafted from the spec alone then freezes a stale
Goal/AC that surfaces only as a material amendment. `{{base_branch}}` is the PR's base
(`gh pr view {{pr_number}} --json baseRefName -q .baseRefName`, or a new PR's intended `--base`). For an
existing PR, `git rev-parse HEAD` must equal `gh pr view {{pr_number}} --json headRefOid -q .headRefOid`, else `[FAIL]`
(check out the PR head first). Fetch the base remote as `setup-review-dir.sh` does (`upstream` if present, else
`origin`; PR #22, issue #196) and list the branch commits in one call, so FETCH_HEAD is not stale:

```bash
git fetch <base-remote> -- {{base_branch}} && git log --topo-order --format='%h %p %s' FETCH_HEAD..HEAD
```

Inspect every commit in that range with `git show --stat <sha>`; for a merge commit (2 parents in `%p`)
use `git show --remerge-diff --stat <sha>`, which shows only what the merge itself changed (a plain
`--stat` lists every base change it brought in). Under remerge-diff,
an octopus merge (3+ parents) gets only a warning and an empty stat,
so use plain `--stat` and tag it `[octopus]`. Inspect them all, not only those after a spec edit: tag a
commit touching `proposal.md`, `design.md` or `specs/` as `[spec]` in the list — a marker only, since a
typo fix or rename there reconciles nothing. If any commit changes Goal-level intent, the contract shown
for confirmation (new-PR draft, or the existing PR's final section) MUST carry a
`Spec vs implementation drift` list (commit, what changed, affected Goal/AC), so the human rules on it
at the **first** confirmation; if none, say so. A failed fetch/log or an empty range is `[FAIL]`: stop,
and never report it as no drift.

For a new PR, the lead drafts this contract from the matching spec/change and writes the complete PR
body to `$CLAUDE_JOB_DIR/pr-body.md` with the Write tool. **Show the drafted contract to the user and
wait for explicit confirmation before creating the PR** — do not launch R1 on a self-drafted,
unconfirmed contract; the confirmed text is the frozen Review Contract for this pass. Then create the PR:

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
Step 3.1, paste the confirmed contract into `prompt-r1.md` (the copy the reviewers consume).

#### Review-in-progress label (issue #587; draft is not a substitute)

Once the PR exists and its contract is confirmed, mark it as "a review is still running" so a repo
with a `Review Gate` check refuses merge until the fixes are in. Draft does not carry that meaning
(yibi-mvp #1111 went `ready_for_review` to merged in 20 minutes), so do not use it instead.

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/review-label.sh add {{pr_number}}
```

| Exit | Meaning | Action |
| --- | --- | --- |
| `0` | Label on the PR, confirmed by read-back | Continue; the label stays until Step 8 "ship", except the exits listed below |
| `10` | The repo has no `review-in-progress` label (`[WARN]` already printed) | Continue; Step 8's summary MUST say `本 repo 沒有 review-in-progress 阻擋機制` |
| other | Any other non-zero exit (`[FAIL]` on stderr: gh failed, read-back disagrees, bad usage, missing gh/jq) | **Stop**; never run R1 on a PR whose label state is unknown |

The label is removed **only** by the exits below, each with
`bash ~/.agents/skills/pr-cycle-deep/scripts/review-label.sh remove {{pr_number}}` (also read-back
confirmed; non-zero is `[FAIL]`, tell the user to remove it by hand — a stuck label blocks merge,
which is the safe direction):

- Step 8, **after** the user replies "ship" (fixes are done by then).
- The Step 7 circuit breaker handing the findings to the user (its "Continue fixing" option re-adds the
  label, following the exit table above).
- The user cancelling, or the live PR turning `MERGED` / `CLOSED` (Step 6 recheck, Step 10 gate).

**Never remove it in Step 5b**: posting the summary precedes the fixes, and yibi-mvp #2449 was merged
6 minutes after its summary with the Critical fix still local. Allow-list:
`Bash(bash /Users/<you>/.agents/skills/pr-cycle-deep/scripts/review-label.sh *)`.

---

### Step 1.5 — Pre-review Check (one script, blocking)

One Bash call — **not** Task agents: each would reload the full base context just to run a fixed
command. The script fetches diff stats and CI state from GitHub (never local `main`), runs
`amplifier-verify.py --pr` (TC coverage + traceability + Test Seam mapping, Check 4), prints a short summary, and writes the full amplifier stdout/stderr
to `.pr-review/pre-review-check.md` (path on the `REPORT=` line):

```bash
python3 ~/.agents/skills/pr-cycle-deep/scripts/pre_review_check.py --pr {{pr_number}}
```

規格根目錄以**受審 repo** 根目錄的 `.spectra.yaml` `spec_dir` 為優先來源，其後仍納入
`openspec`、`docs/openspec` 兩個支援的標準佈局；未有設定檔或 mapping 未含該 key 時只使用
這兩個標準佈局。偵測與查找使用同一份去重後的根目錄集合，保留舊／新路徑以處理跨根目錄
rename；trace checker 的 `--openspec-dir` 必須來自實際選中的 active change，不能在偵測
成功後又回退到 checker 的預設目錄。明確設定的根目錄必須存在且可用；無效／無法讀取的
YAML 或無效根目錄是 exit `2`，即使本次 PR 沒有觸及規格檔也不例外。根目錄／change／archive
查找時越出專案邊界同樣是 exit `2`，不能解讀成「沒有 Spectra change」。

此入口需要 `uv`；它以 locked standalone script 啟動 verifier，安裝 verifier 自己宣告的
YAML 解析依賴，不使用受審 repo 的 Python 依賴，也不要求把套件裝進系統 `python3`。

| Exit | Meaning | Action |
|------|---------|--------|
| `0` | Baseline OK; amplifier clean (no spectra change, all TCs traced, or TC check skipped for a non-`feat`/`refactor` `type:`) | Relay the summary; CI fail/pending is informational here; continue to Step 1.6 |
| `1` | amplifier-verify exit 1 **with** a `[MUST]`/`[SHOULD]` line (a bare exit 1 / traceback is mapped to `2`) | **Do not stop.** Read the report; write MUST findings to `$REVIEW_DIR/final.md` Critical and SHOULD to Important; continue |
| `2` | `gh` failed (auth / PR not found); amplifier-verify exit 2 (invalid/unreadable `.spectra.yaml`, explicit missing/unusable spec root, root/change/archive escape, change dir missing, missing/unparsable testplan on `feat`/`refactor`, HEAD ≠ PR head), exit 1 without a finding line, or did not run; report unwritable; internal error | **Stop** with `[FAIL]`. `gh` causes are the `[FAIL]` lines on stderr and the `- Diff:` / `- CI:` lines; an amplifier cause is in the report's amplifier-verify stderr section |

In the report, check the detected `type:` on the `spectra change detected` line (author-declared;
it decides whether the gate blocks) and any `[WARN]` naming several active change dirs (only the
first was verified). Allow-list: `Bash(python3 /Users/<you>/.agents/skills/pr-cycle-deep/scripts/pre_review_check.py *)`.

Step 2 additionally prepares the fresh Git scope and reports local-main lag. Treat that warning
as diagnostic only: local `main` is never the review base, even when the PR branch has no upstream.

---

### Step 1.6 — Fact-assertion sweep (widen the review surface beyond the diff)

Every voice in Steps 3–4 reads `diff.patch` and nothing else: the mob is broad in *viewpoints*,
**fixed in *scope***. Text elsewhere that this PR just made false is invisible to all of them.

Before Step 2, write 3–7 `X is now Y (was Z)` statements from the PR body + diff. For each, grep the repo (docs, runbooks, checklists, rules — not just code) for text still assuming the old state,
including **arguments whose premise was the old state**. **Re-read your own PR body and commit messages too**: written from intent rather than from a probe, they are the likeliest carriers of an
unverified claim, and on PR #340 this step's first live hit was one the author had asserted there a step earlier. Fix live hits in this PR and add those
files to the review surface; leave historical provenance alone. Report `- "<fact>" -> N hits, M live`.
Where the calling repo has a residual-reference rule, this step is where it gets *executed*, not
merely loaded. **Never skip it on a docs-only PR** — that is exactly when sibling documents rot,
and CI does not check prose.

> Why it is a step and not advice (yibi-mvp PR #933, docs-only, 3 voices × 2 rounds, 25 findings):
> the two worst defects were found by **no voice** — a store data-safety under-declaration and an
> App Store 5.1.1(v) rejection, both asserted in a runbook sitting outside the diff.

---

### Step 1.7 — Red-first gate (the PR's tests must catch the PR's change)

**Blocking.** With production code reverted to the merge-base and the branch's tests kept, a `feat`/`fix` PR's tests must
**fail** and a `refactor`/`perf` PR's must still **pass** (other types `[SKIP]`). The checker is repo-provided — rationale and
limits live in its docstring. Run it only through this one call (Bash `timeout: 600000`), never as hand-split steps: shell
variables do not survive between Bash calls, and a title pasted into a command expands (`${N}`, backticks). The script fetches the
base, passes the title only as a variable, refuses to run mid merge/rebase/cherry-pick/revert or on a dirty tree (staged,
unstaged, untracked or submodule changes; exit `2`), and after the run requires a clean tree and an unchanged HEAD (exit `3`):

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/red-first.sh --pr {{pr_number}} --repo-root "$PWD" --out-dir "$CLAUDE_JOB_DIR"
```

Append its output to `pre-review-check.md`. Exit `0` → continue (includes `[SKIP] red-first: no checker`).
`RED_FIRST_RESULT=unchecked` is also exit `0` but is **not a pass**: the checker said it checked nothing (e.g. every production
change is in a directory it cannot map to tests); treat it like `[EXEMPT]` and require other evidence, e.g. a manual mutation.
Exit `1` (`RED_FIRST_RESULT=fail`) → **stop before Step 2**; add a test that fails on the base code (or restore the refactor's
expectation), push, rerun. Retyping the title to dodge it (`fix` → `chore`) is a material amendment (Step 1), and reviewers
cannot waive it — none of them ran the tests against base code. Exit `2` (tool or precondition error, incl. a traceback, a dirty
tree or an operation in progress) → `[FAIL]` verbatim, stop. Exit `3` or a killed call → the revert may not be restored (or the
checker moved HEAD): show `git status --short` and compare HEAD/branch with the pre-run ones, stop, do not restore by hand (rule 15).
Exit-0 lines carry forward: `[WEAK-RED]` (red came only from an import/compile error, which cannot show the assertion is
meaningful) — Step 3.1 pastes them into `prompt-r1.md`; `[EXEMPT]` (a `Red-first-exempt: <reason>` line) —
the lead may not accept it; Step 8 shows it, and any `[WARN] red-first:` line (checker edited by the PR, checker checked nothing), for the human to confirm.

---

### Step 2 — Code Review (defect detection)

Scope helper 與 Step 5a gate 使用 `uv` 管理的獨立 script 環境，依 PEP 723 metadata 與隨附
`.py.lock` 固定 `markdown-it-py` 依賴；不使用目標 repo 的 Python 環境，也不安裝到全域 Python。
首次執行可能需要下載依賴。缺少 `uv`、lockfile 不符或依賴解析／下載失敗 → `[FAIL]` 停止，
先處理 runtime 前置條件；不得改用裸 `python3` 或退回舊 parser。
部分 uv 版本在 script lockfile 缺失時只警告並忽略 `--locked`；兩個 Python 入口另行拒絕缺鎖檔，
不把「runner 有執行」誤當成「依賴已鎖定」。
`--no-config` 排除目標 repo／使用者設定檔的 index、timestamp cutoff 等干擾，不宣稱清除 `UV_*`
環境變數；若公司 mirror／TLS 設定因此不適用，先備妥明確的 runtime 前置條件，不略過 gate。

先固定審查範圍，再呼叫內建 reviewer。從 PR worktree 執行既有的 fresh-fetch owner：

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/setup-review-dir.sh {{base_branch}}
```

任何失敗都停止。此步產生 `$REVIEW_DIR/diff.patch`、`changed-files.txt` 與
`review-scope.json`（fresh base、HEAD、canonical changed paths），本機 main 落後時會印 WARN。
不要用本機 main 或 reviewer 自行解析的 base 取代它。明確傳 PR 號，維持 report-only：

```text
/code-review {{pr_number}}
```

不要帶 `--fix` 或 `--comment`：在驗證範圍前寫檔或貼 inline finding 都會繞過 admission。
保留 raw 回應，使用 Write tool 將每個 finding 忠實轉成 `$REVIEW_DIR/code-review.json`；
沿用 `schemas/codex-finding.schema.json` 的 `verdict`、`summary`、`findings` envelope 與
`file` 欄位，保留原有 evidence／contract mapping 等附加欄位。file 只放明確檔案路徑，
行號另放欄位；無法確定位置時不得猜測或丟掉該 item，停止並釐清。
真的沒有 finding 時也寫出合法的空 `findings` 陣列，不把錯誤回應轉成 LGTM。

```bash
WT_ROOT=$(git rev-parse --show-toplevel)
REVIEW_DIR="$WT_ROOT/.pr-review"
uv run --no-config --locked --script ~/.agents/skills/pr-cycle-deep/scripts/review_scope.py filter --input "$REVIEW_DIR/code-review.json"
```

Filter 非零退出即停止；HEAD 已移動時從本 Step 重跑，不重用舊結果。
**只有 `code-review-filtered.json` 的 accepted findings 可進入 aggregation／Step 6。**
`code-review-scope.md` 保留被捨棄的原 item、原因與數量，必須原樣帶入 `final.md`；
這些項目不是 evidence-deferred findings，不能再次流入修復清單。全部被排除也不代表
reviewer 已證明 PR 正確，只表示這次 Step 2 沒有可採用的 finding。

#### Auto-apply cleanups (optional)

預設仍是 report-only。使用者明確要求 cleanup 時，也只能由 Step 6 對已通過 scope admission
且符合 Review Contract 的項目動手；不在本流程直接執行 `/code-review --fix` 或未固定 base 的
`/simplify`。兩者可能在過濾前套用與 PR 無關的改動，不能靠事後報告補救。

若使用者另外執行了 cleanup，先檢閱與提交其 diff、確認是否需更新 Review Contract，再從
Step 2 重新準備 fresh scope 與審查。舊 filtered findings 不可跨 HEAD 沿用。

---

### Step 3 — Round 1: Independent parallel review

**Goal**: each voice (Claude / Codex / Gemini) reviews independently **without seeing each
other's findings**, to avoid anchoring bias. Each voice writes its findings to `<voice>-r1.md`
in the review dir (referred to below as `$REVIEW_DIR`).

#### 3.0 — Snapshot preflight (blocking; before any voice is dispatched)

Claude/Codex voices read the working tree; agy R1/R2 read a protected disposable committed-HEAD
snapshot. Concurrent changes can still invalidate the shared diff or another voice's observations,
so keep this common preflight and the after-review HEAD check for every voice.

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/preflight-review-snapshot.sh check
```

| Exit | Meaning | Action |
|------|---------|--------|
| `0` | Snapshot stable | Record the `HEAD=<sha>` from stdout; proceed to 3.1 |
| `1` | Usage error / not a git repo / pinned SHA absent | Fix the invocation; do not dispatch |
| `2` | Unmerged files | **Stop.** Resolve + commit, re-run. `--sha` does **not** override — the tree is half-applied |
| `3` | Merge in progress (`MERGE_HEAD`) | **Stop by default.** To review mid-merge, re-run `check --sha <40-hex>` and require every voice to read via `git show <sha>:<path>`, never the tree |
| `4` | (verify) HEAD moved | Base moved mid-round: re-dispatch, or say so explicitly in `final.md`. Do not silently accept that round |

Once **all** voices have returned their `<voice>-r1.md`:

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/preflight-review-snapshot.sh verify {{head_sha_from_3_0}}
```

> A review-entrypoint gate, **not** a global `PreToolUse` hook: a hook would also block "have a
> reviewer audit this conflict resolution" (legitimate) and cannot gate human review at all.
> It also does **not** replace the conflict-detector step, which asks a different question —
> **GitHub-side** PR mergeability, not local working-tree state.

#### 3.1 — Prepare working directory and shared prompt

所有永久 R1/R2 產物仍放在 `<worktree-root>/.pr-review/`（`$REVIEW_DIR`）。
Step 2 已準備 fresh diff 與 scope；此處不要再次呼叫 setup、失效剛通過的 Step 2 結果。
若 HEAD 改變，回 Step 2。將確認過的 contract 寫進 `prompt-r1.md`。

agy R1/R2 以 inline prompt 執行，cwd 與絕對 `--add-dir` 指向一次性 HEAD snapshot，
不是原工作樹。macOS 需可用的 `sandbox-exec`，Linux 需可用的 `bwrap`；
無 backend、backend 不可用、tracked tree 有未提交修改或衝突時，該 voice 明確失敗，
**不得改回直接在原工作樹執行**。OS 防護使原工作樹、Git metadata 與 snapshot 原始碼不可寫；
暫存 home／scratch／log 由 helper 管理，結束或中斷後回收，永久 log 回到既有 review 目錄。
若 OS 拒絕清理，helper 會非零退出並列出殘留工作目錄；該 voice 不算成功。
先依診斷處理剩餘狀態，不得把留下暫存資料的執行回報為已完成回收。
上游 agy 的 command 探索仍使用既有權限旗標，但旗標不再是檔案系統的安全邊界。

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
Bash(bash /Users/<you>/.agents/skills/pr-cycle-deep/scripts/preflight-review-snapshot.sh *)
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
<if pre-review-check.md has [WEAK-RED] lines: "## Weak-red tests (inspect for tautology)" + those lines>

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
- Test coverage gaps (critical paths not tested); tests whose expected value is computed the way the
  code computes it, or that mock this repo's own modules (mocks belong at external boundaries only)
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
| Tautological or implementation-coupled test | The assertion line plus either the production line its expected value re-computes, or the in-repo module it mocks / the call count it asserts / the DB row it reads instead of the interface. |
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
| `pr-test-analyzer` | Test coverage gaps; tautological / implementation-coupled tests, starting with any `[WEAK-RED]` tests from Step 1.7 |
| `comment-analyzer` | Documentation / comment accuracy |

> **Mutation isolation**: `pr-test-analyzer` verifies tests by mutation, which **edits files in
> the shared worktree in place**, while the other three subagents are reading those same files.
> `.claude/rules/17-shell-script-authoring.md` states it directly: "Do not run mutation tests on a shared
> worktree file while a review agent is reading it. … Sequence them: finish the review round,
> collect every report, *then* mutate." So instruct `pr-test-analyzer` to either **hold its
> mutations until the other three have returned**, or run them on a copy outside the worktree.
> Whichever it does, require it to restore each mutated file and report `git status --porcelain`
> in its final output — dispatching all four at once without this note makes the skill's own
> Step 3.2 contradict rule 17.

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
Step 2 already produced, so all three voices review the identical diff. Raw output lands in
`codex-r1-raw.md` — **do not read it in the main context**.

Review stages pin `-m gpt-6-astra` and gate on codex-cli >= 0.154.0 (0.149.0 answers it with a 400); the extract pins the cheap `-m gpt-5.6-luna` plus `--ignore-user-config` (issue #444).
If the gate fails: `npm install -g @openai/codex@latest` (asdf node also needs `asdf reshim nodejs`). A slug in `models_cache.json` only applies to the CLI matching that file's `client_version`.

###### Stage 2: Extract (compress verbose raw markdown into structured JSON)

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/codex-r1-stage2.sh
```

###### Stage 3: Render (lead reads JSON → writes compact markdown)

Lead reads `$REVIEW_DIR/codex-r1.json` with the Read tool and branches on the result:

**JSON valid** (valid JSON with `verdict` / `summary` / `findings` fields) → use the Write tool to render `$REVIEW_DIR/codex-r1.md` (compact markdown, sorted by severity: critical → important → actionable_nit).

**Carry `contract_mapping` and `evidence` through to the rendered markdown** as
`- Contract mapping:` / `- Evidence:` lines on each finding. Step 5's Evidence gate reads those
two lines; dropping them here makes every Codex finding fail the structure check as "no evidence"
even though the reviewer supplied it. If a finding's `evidence` is an empty string, render the
line as `- Evidence: (reviewer did not supply)` rather than omitting it — the gate must be able
to tell "reviewer gave none" from "the pipeline lost it".

**JSON invalid** (not valid JSON or missing fields) → do not render; fall back: Read
`$REVIEW_DIR/codex-r1-raw.md`, manually summarize in the main context, Write compact markdown to
`$REVIEW_DIR/codex-r1.md`, then note in final.md "Codex voice used raw form this round; main context load is higher".

##### Gemini voice (when GEMINI_OK)

agy does not accept a combined stdin prompt + diff path; concatenate into a single file first:

###### Stage 1: Native review (raw output lands on disk, does not enter main context)

> **Execution/security contract**: run the script verbatim; never append `$?` logic or redirects.
> It inlines prompt+diff (never `@file`, issue #153) and validates output with `agy_validate.py`.
> R1/R2 run in a protected HEAD snapshot with a private HOME; they do not delete shared scratch.
> `--dangerously-skip-permissions` permits command exploration inside the OS write boundary.
> Original-tree before/after comparison remains an audit signal, not the isolation mechanism.
> Use trusted repos: filesystem write isolation does not prevent reading secrets or network access.
> Stage 2 keeps its existing CLI sandbox. On failure read `$REVIEW_DIR/gemini-r1.stage1.log`.
>
> **`subagent` permission class**: invoked by this skill, not the user — allow-list by this
> script's own absolute path, never a bare `Bash(agy:*)`. `--sandbox` was empirically confirmed
> (agy 1.1.8; re-verified 1.1.12, 2026-08-13) to auto-deny the `command`-class tool a review uses
> to explore code — `read_file`/`ListDirectory` within `--add-dir` stay allowed, only `command` is
> blocked, so widening `--add-dir` can't fix it; headless `-p` can't grant it. Re-verify on upgrade.

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/agy-r1-stage1.sh
```

The script pins `--model 'Gemini 3.8 Flash (High)'`. Do not remove the flag: `agy`'s
auto-select can choose another Gemini tier, and its model list also contains Claude Sonnet/Opus —
an auto-selected Claude would silently collapse this voice into the same family as the Claude lead,
defeating the cross-family premise with no warning. `gemini-3.8-flash-high` was verified with
agy 1.1.25 in Taiwan on 2026-09-03; the High tier preserves review reasoning depth while using the
newer Flash generation. `agy models` lists the valid display names; an invalid value fails loud and
prints the list. Raw output lands in `gemini-r1-raw.md` —
**do not read it in the main context**.

###### Stage 2: Extract with Gemini 3.8 Flash (High)

> **Execution note**: the script writes stderr to `$REVIEW_DIR/gemini-r1.extract.log`; stdout only
> outputs "agy R1 Stage 2 complete". **Run directly — do not append `> $CLAUDE_JOB_DIR/foo.log 2>&1`**
> (harness auto-capture is redundant here; see rule 16 **(2) Bash redirect `>`** for `Bash(verb:*)` allow-list patterns) —
> on failure, Read `$REVIEW_DIR/gemini-r1.extract.log` for the full error.

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/agy-r1-stage2.sh
```

The extract stage pins the same `Gemini 3.8 Flash (High)` model as review and debate, so every agy execution path in this skill uses the requested model rather than auto-selection.

###### Stage 3: Render (same as Codex voice: lead reads JSON → writes compact markdown)

Lead reads `$REVIEW_DIR/gemini-r1.json` with the Read tool and branches:

**JSON valid** → use the Write tool to render `$REVIEW_DIR/gemini-r1.md` (same format as Codex compact markdown, **including the `Contract mapping:` / `Evidence:` carry-through** described above).

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
- Blockers exist、無 dispute、lead 承諾**全數照原評級採納並修復** → 可跳過 Step 4，回報 `R2 skipped: lead adopts all blockers`（**採納 ≠ 免驗證**：仍依 Evidence gate 復現；lead 降級/不修/有異議或任何 dispute → 照常跑 Step 4）。

This gate applies on the initial review and every bounded re-review pass（第二個出口見 openspectra #100-#104／issue #361）。

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

> **Security note**: `agy-r2.sh` uses the same protected HEAD snapshot and private HOME as Stage 1.
> Its permission-bypass flag permits command exploration inside OS write containment, not source writes.
> Keep the trusted-repo boundary and the per-script allow-list; do not use a bare `Bash(agy:*)`.

Only send to available voices (CODEX_OK / GEMINI_OK).

Claude voice: the lead writes `$REVIEW_DIR/claude-r2.md` after reading r1-aggregate — no subagents needed (avoid 4×4 = 16 reviews generating too much noise).

---

### Step 5 — Aggregator synthesis

After reading all R1 plus any activated R2, produce `$REVIEW_DIR/final.md`, graded per the
[Review Severity Standard](#review-severity-standard-rfc-2119) (Critical = MUST, Important = SHOULD,
Actionable NIT = MAY). Blocking is decided by the Evidence gate below; NIT never blocks any round.

Step 2 只讀取 `code-review-filtered.json`，不得從 raw 回應或被排除的項目重建候選。
將 `code-review-scope.md` 的整個 owned marker 區塊原樣保留於 `final.md`（含零筆與捨棄數量），
不要在重建 final 報告時覆蓋掉它，也不要覆蓋 pre-review amplifier 已產生的 findings。
若本輪重新準備過 scope，舊 Step 2 結果已失效；MUST 重跑 Step 2 reviewer、正規化與 filter，
再用本輪 filtered 陣列重建 final 的來源編號與去向；不得沿用舊 CR 列或手寫 filtered JSON。

按 filtered `findings` 陣列順序（從 1 起）給 Step 2 來源編號 `CR-1`、`CR-2`……；
在 final 的對應 finding 下加獨立列 `- Code-review source: CR-1`。合併重複 finding 時，
同列列出全部來源，例如 `- Code-review source: CR-1, CR-2`。每個來源只出現一次；
降級／Outside contract／Disputed 仍保留來源，WITHDRAW 則移到 `## Withdrawn` 記錄原因與來源，
不留在修復清單。其他 voices／amplifier 不編 CR 號；不得用總數摘要或 scope audit 代替逐項列出。
來源列必須是獨立的純文字 hyphen list item；可頂格或相對所屬清單縮排（包含多位數與多層清單）。
`markdown-it-py` 的 CommonMark tokens 決定正文／code／HTML 結構，不以正規表示式猜縮排。
indented code、code fence、HTML 註解與 audit 不算來源；inline code 中的 comment／marker 字面值
不改變解析狀態。同一個 `Code-review source` 欄位的 bullet、大小寫或冒號格式錯誤會被拒絕；
不對一般 finding 標題做模糊比對。觸及 parser 的安全深度上限時 exit `2`，不得把被省略的內容當成零筆。

| Grade | Condition | Action |
| --- | --- | --- |
| **Consensus Critical** | ≥2 voices mark Critical with no DISAGREE | Must fix |
| **Consensus Important** | ≥2 voices mark Important with no DISAGREE | Must fix |
| **Disputed** | 1 voice marks Critical/Important; others DISAGREE | List the dispute; user decides |
| **Single-voice Critical** | 1 voice marks Critical; others did not mention | Lead MUST execute before adopting — do NOT skip by reasoning alone: ① Extract the finding's claimed pattern (the specific syntax, string, or construct the finding says is problematic) ② `grep -rn '<pattern>' <relevant-dirs>` — report hit count ③ Zero hits + pre-existing limitation (old code also didn't handle it) → demote to Deferred with `Grep verification: <command> → 0 hits` ④ Nonzero hits → confirm as Consensus Critical ⑤ Can't grep (no concrete pattern) → list as Disputed. (4× recurrence: PR #626/#653/#815/#1774 — lead adopted single-voice Criticals by reasoning without grepping actual usage; all turned out to be zero-hit pre-existing limitations.) |
| **Actionable NIT** | Any 1 voice marks NIT and it's not subjective preference | **Deferred — never blocks**, any round. Lead MAY fix trivially in-round; doing so is not a gate |
| **Withdrawn** | Marked WITHDRAW in R2 | 移出修復清單；Step 2 來源留在 Withdrawn 區塊供 Step 5a 核對 |
| **Voice unavailable** | That voice failed R1/R2 twice in a row | Note in final.md; do not block |

#### Contract mapping gate

A Critical / Important finding is eligible for the Evidence gate only when `Contract mapping:` is
one of: `AC-<id>`, `repo baseline: <path/rule>`, or `unaccepted risk: <description>`. Missing or
invalid mapping is moved to deferred with its original text and reason preserved. Work wholly inside
Non-goals, Follow-ups, or a documented accepted boundary is non-blocking. An accepted risk needs all
five fields from Step 1, including `Accepted by:`; a voice or lead cannot accept it for the human.
Repo security/data-integrity baselines cannot be waived by any Review Contract section.

> **Contract mapping validation**: before promoting, lead MUST verify the reference exists —
> the AC-ID is in the Review Contract, the `repo baseline:` path/rule exists in the repo, the
> `unaccepted risk:` is not already accepted. Voices can write fabricated references; do not
> rely on cross-debate to catch omissions. (Source: yibi-firmware PR #44 — a NIT carried no
> mapping; caught only because Codex DISAGREEd in R2.)

#### Evidence gate

A Critical / Important finding blocks merge **only** if it carries a valid `Evidence:` in the form
its type requires (see Evidence forms in the R1 prompt). The gate is applied at aggregation, before
any fixing, and is **tiered by cost** so most rejections execute nothing:

| Tier | Applies to | Action |
| --- | --- | --- |
| Structure check | any finding | `Evidence:` missing or not the required form → **demote immediately, executing nothing** |
| Hallucination tell | any with well-formed evidence | evidence describes what *should* appear rather than what *does* → **screen and demote** if confirmed (see note below); Critical still reaches Verify as backstop |
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

> **Evidence hallucination tell** — a reviewer can fabricate both defect and evidence in valid
> form. The tell: evidence reads like a **template** ("one should see X") rather than **concrete
> data** ("running `grep -rn '^## 7' docs/specs/` returns 0 hits"). Screen for this before
> spot-checking Important findings; the Verify tier catches it for Critical. (Source:
> yibi-firmware PR #44 — agy's `Evidence:` described the expected form, not actual output;
> `grep` refuted the claim and the heading matched the template and 15 sibling specs.)
>
> **Single-voice [P0]/[Critical] → verify with a repro before acting — and re-verify before *citing* a past
> verdict** (esp. CLI flag-parsing / runtime claims, which often reason from a plausible-but-wrong model).
> **Record the tool version**: a stored verdict expires when the tool changes. Example (PR #157 → #229): agy's
> `[P0] --print eats --add-dir` was once refuted by `printf 'reply ALPHA' | agy --print` → `ALPHA`; on **agy 1.1.2**
> that no longer holds and the finding is now correct. The `@file` caution stands: inline via `-p "$CONTENT"`, never `@file`.

`final.md` format:
範本的來源列只用於 Step 2 findings：將 `<n>` 換成實際索引，合併時用逗號分隔全部 CR 號；
其他 voices 的 finding 刪掉該列，不留下佔位符或附註文字。

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
   - Code-review source: CR-<n>

## Consensus Important (must fix)
1. <finding>...
   - Code-review source: CR-<n>

## Actionable NIT (deferred — never blocks; fix opportunistically)
1. <finding>...
   - Code-review source: CR-<n>

## Deferred for lack of evidence (not blocking; reason stated per item)
1. <finding> — demoted: <reason>... (For single-voice Critical demotions, include `Grep verification: <command> → <N> hits` in the demotion reason.)
   - Code-review source: CR-<n>

## Outside contract (not blocking; mapping reason stated per item)
1. <finding> — <Non-goal / accepted boundary / Follow-up / invalid mapping>...
   - Code-review source: CR-<n>

## Disputed (user decides)
- Voice X argues Critical: <reason>
- Voice Y disagrees: <reason>
- Lead recommendation: <decision guidance>
- Code-review source: CR-<n>

## Withdrawn (not in fix list)
1. <finding> — withdrawn: <reason>
   - Code-review source: CR-<n>

## Voices unavailable
- <voice>: <reason>

<paste code-review-scope.md verbatim, including its owned markers and rejected-item audit>
```

Report the final.md summary to the user and wait for Disputed item decisions before proceeding to Step 5a.

**Checkpoint (context lifetime).** With the Write tool, write `$REVIEW_DIR/state.md`: PR number,
base branch, baseline SHA, `head:` (PR `headRefOid`), re-review round, `ci_command:` (Step 6),
`disputed:` (each Disputed item + the user's ruling), and `next: Step 5` while any Disputed item
lacks a ruling, else `next: Step 5a`; rewrite `head:` / `next:` at every later step boundary. Later steps need nothing beyond `$REVIEW_DIR` (`prompt-r1.md` = frozen contract,
`final.md` = blocking set), so this human pause is the cheapest place to shed context: tell the
user they may `/compact`, or open a fresh session and run `/pr-cycle-deep #<PR> --resume`.

---

### Step 5a — 收下筆數與 final 列出筆數 gate（blocking）

每次進入 Step 5b **或 Step 6** 前（含 `--resume` 直接跳入與 Step 7 重彙整），MUST 從 PR worktree 執行：

```bash
WT_ROOT=$(git rev-parse --show-toplevel)
REVIEW_DIR="$WT_ROOT/.pr-review"
uv run --no-config --locked --script ~/.agents/skills/pr-cycle-deep/scripts/check_review_counts.py --review-dir "$REVIEW_DIR"
```

核對 `code-review-filtered.json` 的 `findings` 筆數與 final 正文 CR 來源筆數，並要求來源編號
一一對應，防止「漏一筆、重複一筆」仍以相同總數過關；code fence、indented code、HTML 註解
與 scope audit 不計入來源，但 audit 內的 fence 仍須完整；引用的 marker 不當成 audit 邊界。
Gate 與 scope writer 共用 `review_markdown.py` 的結構解析與 audit span；scope 的 finding 准入規則不變。
零筆也必須有合法 filtered JSON 與非空 final，得到 `accepted=0 listed=0` 才通過。
Exit `0` → 才可進 Step 5b／6；`1` → 筆數／來源不符；`2` → 缺檔、JSON／來源格式錯誤、
空 final、未閉合 fence／HTML 註解、重複或不完整 audit markers。
任何非零 MUST 停止，不貼 PR、不進 Step 6；filtered JSON 缺漏／非法 → 回 Step 2 重做 review/filter，
final 缺檔／為空／格式或來源不符 → 回 Step 5 重新彙整並補齊去向；checkpoint 指向該修復步驟，修好再跑 Step 5a。
沒有 `[FAIL] review-count` 診斷的非零（例如 traceback／`can't open file`）屬執行錯誤，
先查 stderr 與安裝版本；不得修改 review 資料湊數，也不得從 worktree 執行 `make install`。
此 gate 不改變 finding 的 blocking 等級；final 修改後必須重新核對。

---

### Step 5b — Post review summary to PR

先執行 Step 5a 並確認 exit `0`（即使 resume 的 `next:` 是 Step 5b 也不能跳過）。
在修復前將彙整結果貼到 PR，留下決策紀錄。每個 Bash call 重新取得 `REVIEW_DIR`：

```bash
WT_ROOT=$(git rev-parse --show-toplevel)
REVIEW_DIR="$WT_ROOT/.pr-review"
gh pr comment "{{pr_number}}" --body-file "$REVIEW_DIR/final.md"
```

- **exit 0** → report the comment URL.
- **non-zero** (auth / network / PR not found) → `[WARN] 無法貼 review summary 到 PR`; show the user the manual command, then **continue to Step 6** (posting must not block fixes).

First-time use may prompt for permission → add `Bash(gh pr comment:*)` to `settings.local.json`
(rule 16 safe form). MVP posts one comment here; re-post after Step 7 only if consensus materially changed.

Do **not** touch the `review-in-progress` label here: the fixes have not been made yet (see Step 1).

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

進入修復前 MUST 通過 Step 5a；`--resume` 直接跳入 Step 6 也不能省略。
gate 非零先回指定步驟補齊 review 產物，不得先修程式。

Delegate the fix loop to **one** `general-purpose` Task subagent. Reading code, editing and
iterating on CI are the most turn-heavy part of the cycle; in the lead's context every one of
those turns re-reads the whole review history. First pick the CI command yourself (Makefile
`ci`/`test` target, else `uv run pytest` / `npm test` / `go test ./...` / `flutter test`) and record
it as `ci_command:` in `state.md`. Pass the last verified PR `headRefOid` from that checkpoint
as `expected_pr_head` — not a newly observed, unreviewed head. Both the lead and a fix subagent
MUST use the same **pre-push gate**, immediately followed by the push in one `&&` chain:

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/preflight-pr-push.sh "{{pr_number}}" "{{expected_pr_head}}" && git push
```

`preflight-pr-push.sh` requires `git`, `gh` and `jq` on PATH. It is read-only: only live `OPEN`, the expected PR head, a matching local
branch, and a local fast-forward pass. Exit `2` means `MERGED`/`CLOSED`; exit `3` means the
branch/head moved or local history is not a fast-forward; exit `1` means invalid input,
unavailable tools/API, malformed metadata, or invalid local state. **Every nonzero blocks
the push**; preserve local fix commits and report the reason. Never refresh the expected SHA
blindly, force-push, or retry an unguarded push to bypass the gate.

This applies to each existing-PR fix push, including CI fixes and conflict/base-update fixes.
The initial branch publication in Step 1 has no PR yet and is outside this gate. A successful
check is **not an atomic lock** across the GitHub API and Git push: the PR could change in that
short interval, so retain the post-push status/head checks below.

Prompt (fill in the real `$REVIEW_DIR`, `<ci_command>`, `<pr_number>` and `<expected_pr_head>`):

```text
Fix the blocking findings in $REVIEW_DIR/final.md in order: Consensus Critical, Consensus
Important, then the Disputed items ruled "fix" in $REVIEW_DIR/state.md `disputed:`; Actionable NIT
only if trivial. The frozen Review Contract is in $REVIEW_DIR/prompt-r1.md — do not expand scope.
For Step 2 findings, only code-review-filtered.json is admissible. Never fix raw or scope-rejected
items from code-review.json or the final report's scope audit.
Run <ci_command> and fix until it passes. Commit each batch with a message describing what was
fixed (never "fix review comments"). Immediately before EACH push, run:
bash ~/.agents/skills/pr-cycle-deep/scripts/preflight-pr-push.sh <pr_number> <expected_pr_head> && git push
The initial expected_pr_head is the lead-supplied reviewed SHA. After a successful push, the
next batch may use that successfully pushed commit SHA; never adopt an arbitrary new remote
head to bypass a refusal. Any nonzero gate result means STOP without pushing or retrying;
keep local fixes and return the gate status/reason. Do not touch .pr-review/. Reply with only:
commit SHAs, each finding FIXED / NOT FIXED + one-line reason, CI exit code, and push status
(PUSHED or BLOCKED with the gate output).
```

If the subagent reports BLOCKED, route the observed state before the receipt checks:
`MERGED` → stop the cycle, run Step 1's `review-label.sh remove`, and go to Step 11 without another
push; `CLOSED` → run Step 1's `review-label.sh remove`, stop and wait for the user; query/metadata failure or branch/head mismatch → stop and resolve the reported
problem before authorizing any new push. Local commits remain available for recovery.

Task call errors or returns empty → `[FAIL]` stop. For PUSHED, **verify, do not trust the summary** —
any mismatch is `[FAIL]` stop: `git status --porcelain` empty; `git log --oneline <baseline>..HEAD`
non-empty if anything is FIXED; `gh pr view {{pr_number}} --json headRefOid -q .headRefOid` equals
`git rev-parse HEAD` (the push landed). Re-run CI yourself in one call, gating on its exit code
(`>|`: plain `>` fails under noclobber on a second Step 6 pass; Read the log only on failure):
`REVIEW_DIR="$(git rev-parse --show-toplevel)/.pr-review"; <ci_command> >| "$REVIEW_DIR/ci-step6.log" 2>&1`.
A NOT FIXED blocking item goes to the user; the subagent's "CI passed" is never the gate.

**Recheck PR status before looping back into re-review.** A group re-review (Step 7) is
expensive — do not spend it on a PR that is no longer open or mergeable. After pushing, re-query
the live PR state:

```bash
gh pr view "{{pr_number}}" --json state,mergeable,mergeStateStatus -q '.state + " / " + .mergeable + " / " + .mergeStateStatus'
```

Route by the result. The decision table is authoritative — do not proceed on a row that says STOP:

| `state` | `mergeStateStatus` / `mergeable` | Meaning | Action |
| --- | --- | --- | --- |
| `MERGED` | any | Someone merged the PR out-of-band | **STOP the cycle** — skip re-review; run Step 1's `review-label.sh remove` and tell the user; go straight to Step 11 (archive / Jira). Do not push more. |
| `CLOSED` | any | PR closed without merging | **STOP** — run Step 1's `review-label.sh remove`, surface to the user and wait; do not continue. |
| `OPEN` | `DIRTY` / `mergeable=CONFLICTING` | Fixes (or a base advance) created merge conflicts | Resolve conflicts against `{{base_branch}}`, commit, push, then re-run this recheck before Step 7. |
| `OPEN` | `BEHIND` | Base branch advanced since this branch forked | Update the branch from `{{base_branch}}` (merge or rebase per repo convention) and push, so Step 7 R1/R2 review against the current base — otherwise findings are computed against a stale base. |
| `OPEN` | `CLEAN` / `BLOCKED` / `UNSTABLE` / `HAS_HOOKS` / `UNKNOWN` | Open and not conflicting (may still await CI/approvals) | Continue to Step 7. |

If `gh pr view` itself errors (auth / network), stop and report — an empty result is not "OPEN".

---

### Step 7 — Group re-review (bounded to two rounds)

The re-review loop is **bounded**: Round 1, then at most Round 2, then it exits — to a merge or to
human adjudication. There is no "run one more round to see."

**Terminology**: these **re-review passes** (Round 1 / Round 2 here) are distinct from the per-pass
cross-debate **rounds** (Step 3 R1 independent + Step 4 R2 debate). Each re-review pass internally
re-runs Step 3, and Step 4 only if the Step 3.4 gate activates — so one pass can contain its own R1/R2.

| Round | Review surface | Can block merge | On exit |
| --- | --- | --- | --- |
| Round 1 | the **full diff**; record the baseline head SHA (`git rev-parse HEAD`) before Step 6 fixes — the next round's surface is defined relative to it | evidenced Critical / Important | 先完成 Step 5 → 5a；gate 非零停止，通過後 blocking set empty → Step 8；non-empty → Step 6 fix, then Round 2 |
| Round 2 | only `baseline..HEAD` (the commits this round's fixes added) | evidenced Critical only | 先完成 Step 5 → 5a；gate 非零停止，通過後 blocking set empty → Step 8；non-empty → circuit breaker (human adjudication) |
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

本次 refresh 會刪除舊 `code-review-filtered.json`。在派出 Step 3 voices 前，MUST 重跑 Step 2
的 `/code-review {{pr_number}}` → 正規化 → filter（不要再重跑 setup）；即使零 findings 也要
由 filter 產生本輪合法空陣列。保留上一輪 final 作歷史後，依新陣列重新編 CR 號與彙整，
不能以不存在的 filtered JSON 進 Step 5a，也不能保留上一輪來源列來湊數。
Round 2 的 Step 2 仍更新完整 PR 的 source inventory；`baseline..HEAD` 限制的是 mob review 與
本輪 blocking 判定，不是 scope filter 的檔案准入。CR 號依新 filtered 陣列分配；落在 fix surface
外的項目標為 `Outside Round 2 contract` 並保留來源，不據此重開修復迴圈，也不偽造零筆輸入。

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

Before showing this prompt, run Step 1's `review-label.sh remove {{pr_number}}` and tell the user the
label is off: from here a human owns the decision, and a PR that still carries the label would
stay unmergeable while they decide. Wait for explicit instruction, then act on the choice:

- **False positive**: continue to Step 8 with the label already off. Step 8's summary MUST say it was
  removed early by the circuit breaker (merge was unblocked from then).
- **Continue fixing**: run `bash ~/.agents/skills/pr-cycle-deep/scripts/review-label.sh add {{pr_number}}`
  and follow Step 1's exit table (exit 0 continue; exit 10 note it for the Step 8 summary; any other
  exit: **Stop** and report to the user, do not resume fixing), then go to Step 6.
- **Return to redesign**: **Stop** the cycle; the label stays off.

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
- Claude: LGTM / NEEDS_CHANGES
- Codex: LGTM / NEEDS_CHANGES / N/A
- Gemini: LGTM / NEEDS_CHANGES / N/A

## Red-first (always shown; from pre-review-check.md)
- <verdict / [SKIP] reason>; <each [EXEMPT] or [WARN] red-first: line — needs your confirmation>

## Merge blocking (review-in-progress label)
- <held during review, removed on "ship" / 本 repo 沒有 review-in-progress 阻擋機制 (Step 1 exit 10) / removed early by circuit breaker at Step 7 (merge was unblocked from then)>

## Change hotspots (top 3 places most worth human eyes)
1. <file:line> — <why it's a hotspot>
2. ...

## Manual Verification (unchecked `- [ ] MV-NNN` items of the change's testplan.md; omit if none)
- MV-NNN: <observable check> — human result: pass / fail
```

Manual Verification items are testplan TCs no test can automate: list them by running Step 11a's
`check_testplan_trace.py --strict` command now (its `manual-open` lines), ask the human to confirm
each, post the results as one PR comment, then mark confirmed items `- [x]` in testplan.md.

Show the summary and hotspots to the user. Get the path, then reply conversationally so they can `cat` it:

```bash
WT_ROOT=$(git rev-parse --show-toplevel)
REVIEW_DIR="$WT_ROOT/.pr-review"
echo "$REVIEW_DIR/human-summary.md"
```

Reply (substitute the echoed path for `<path>`): "Contract satisfied and blocking set empty. Three hotspots in `<path>`. Raise concerns here — I (reviewer lead) respond immediately;
reply 'ship' to proceed to Step 9 CI."

User raises a concern → lead responds directly (citing R1/R2 original findings if needed); unresolvable concern → return to Step 6 to fix; resolved → user replies "ship" before proceeding to Step 9.

**On "ship" (and not before)**, remove the `review-in-progress` label so merge is unblocked once the
fixes are in; a user cancel takes the same path:

```bash
bash ~/.agents/skills/pr-cycle-deep/scripts/review-label.sh remove {{pr_number}}
```

Non-zero is `[FAIL]`: report it, tell the user to run `gh pr edit {{pr_number}} --remove-label review-in-progress`
by hand, and do not continue to Step 9 until they confirm.

---

### Step 9 — CI Check

Wait for GitHub Actions to pass:

```bash
gh pr checks "{{pr_number}}" --watch
```

CI fails: reproduce locally (using CI command from Step 6) → fix → commit → **Step 6 guarded push** → wait again.
Local CI is authoritative: when CI and local differ, trust local; check for CI environment differences.

---

### Step 10 — Merge

**Pre-merge gate: confirm PR is still OPEN.** Re-run Step 6's "Recheck PR status" `gh pr view` query, but route as below, **not** by Step 6's table (it routes to Step 7).
Why: a bump push after an out-of-band merge silently recreates the deleted branch (issue #462).
`MERGED` → **STOP**: no bump, merge, or push; go to Step 11. `CLOSED` → **STOP**; surface to the user and wait.
Either way, if the label is somehow still on, run Step 1's `review-label.sh remove` (a no-op when it is already off).
`gh pr view` error → stop and report (empty ≠ OPEN).
`OPEN` + `DIRTY` / `CONFLICTING` / `BEHIND` → update from `{{base_branch}}`, use the **Step 6 guarded push**,
return to Step 9 (CI), then re-run this gate. Any other `OPEN` → continue to the version-bump check below.

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

Before archiving, gate on the testplan trace (resolve `SDD_ROOT` with spectra-amplifier's
"Plugin 資源路徑解析" block; add `--openspec-dir <dir>` if openspec is not at the repo root):

```bash
python3 "$SDD_ROOT/scripts/check_testplan_trace.py" --strict --change "{{change_name}}"
```

Exit 1 → stop and report the FAIL lines (unbound auto TC, orphan, mismatch, collision, open MV
item); exit 2 → configuration error, stop and report stderr. After exit 0 and confirmation:

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
| Step 0 detects only one external voice (Codex or agy, not both) | Enter 2-voice mob (Claude + that voice); normal workflow |
| Codex detected but auth failed | `codex login`; or `export OPENAI_API_KEY=...` |
| agy detected but auth failed | Run `agy` to complete OAuth; or `export GEMINI_API_KEY=...` |
| agy went agentic in a nested worktree (wrong-target review / brain-artifact pointer / `Error: timed out`) | R1/R2 inline prompts (no `@file`), use a private HOME without old scratch, and run `agy_validate.py`; they leave shared scratch untouched. Brain artifacts are rescued before private HOME cleanup. Stage 2 retains its existing extraction sandbox/cleanup. Validator failure means the voice failed. Exit **124** means timeout: partial output is quarantined as `*.timeout-partial*`, never aggregate it; inspect `*.agy.log` for `RESOURCE_EXHAUSTED` or use `AGY_PRINT_TIMEOUT_SECS` (1–570, default 480). |
| agy background bash `>` redirect output not updating target file (unverified) | If this occurs: switch to synchronous bash call (without `run_in_background`) |
| Codex Stage 1 `codex-r1-raw.md` is empty (review missing) | Stage 1 now uses `codex exec ... > codex-r1-raw.md` (stdout); read `$REVIEW_DIR/codex-r1.stage1.log` (stderr) for the error. For the `codex exec \| tee` stages (Stage 2 / R2), `set -o pipefail` keeps `$?` reflecting the failing command in the pipeline (bash/zsh) |
| Why Stage 1 uses `codex exec`, not `codex review --base` + a guard prompt | `codex review --base` and a positional `[PROMPT]` are mutually exclusive (codex-cli 0.142.5: `the argument '[PROMPT]' cannot be used with '--base <BRANCH>'`), so the skill-hijack guard cannot ride on `codex review`. Stage 1 drives the review through `codex exec` with the guard on stdin instead (issue #194). Do not "fix" it back to `codex review --base` |
| codex Stage 1 runs against wrong repo | The stage-1 script passes `codex exec -C "$WT_ROOT"`, pinning the repo root; ensure you run the script from inside the worktree (avoid tools like gstack changing CWD, AP3 Sub-class A) |
| A voice fails R1/R2 twice consecutively | Mark as unavailable; do not block; aggregate report notes the reason |
| R2 receives r1-aggregate that is too large for voice to process | Remove raw diff from r1-aggregate; keep only findings; diff was already processed in the r1 prompt |
| Round 2 ends with unresolved blocking findings | Trigger circuit breaker; hand remaining findings to user with the three-option decision (no third round) |
| User chooses to ignore a disputed finding | Add a Known Issues section to the PR description with the reason |
| User raises new concern during human quick pass | Reviewer lead responds immediately; unresolvable → Step 6; resolved → wait for "ship" |
| When does R2 run? | All active voices always run independent R1. Run R2 only when Step 3.4 finds a candidate blocker the lead does not adopt as-graded, or a blocking dispute. Two legal skips: a clean R1 (`R2 skipped: no contract-blocking candidate or dispute`), and lead-adopts-all (`R2 skipped: lead adopts all blockers` — 採納 ≠ 免驗證，Evidence gate 照跑). |
| Linter / type-check fails | `ruff check --fix` / `eslint --fix` / `mypy follow_imports = skip` etc. |
| Security scanner fails | bandit `# nosec BXXX` etc. ignore comments; explain reason in PR |
| spectra archive validation fails | `spectra analyze {{change_name}}`; fix then archive; `--no-validate` requires explicit user instruction |
| Jira: cannot detect key / transition unclear / MCP auth error | Ask user for the key (`PROJECT-123`), or confirm there is no associated ticket and skip; list transitions and ask user to confirm; Atlassian MCP requires OAuth — prompt user to authorize on claude.ai |
| Codex/Gemini extract returns invalid JSON, JSON missing schema fields (`verdict` / `summary` / `findings`), or extract fails 2× in a row | Follow Stage 3 if/else: Read `$REVIEW_DIR/{codex,gemini}-r1-raw.md`, manually summarize in main context as compact markdown, Write to `$REVIEW_DIR/{codex,gemini}-r1.md` (do not cp raw → compact — verbose raw would enter r1-aggregate); note in final.md "{{voice}} voice used raw form this round, main context load higher". 2 consecutive extract failures → path C: lead extracts the compact form from raw in the main session without calling codex/agy again (slower, workflow not blocked) |
| Extract prompt path missing (`~/.agents/skills/pr-cycle-deep/prompts/extract-r1.md`) | Skill not installed; run `make install` in yibi-stack to create the symlink; verify: `ls ~/.agents/skills/pr-cycle-deep/prompts/extract-r1.md` should return the path, not "No such file" |
| User skipped bump but needs a version tag later | Create a release branch, run [`/bump-version`](../bump-version/SKILL.md) on it, then open a PR to merge into main (CI pass + CHANGELOG confirmed is sufficient; no full review cycle needed; if main has new commits, CHANGELOG may include extra entries — verify manually) |
