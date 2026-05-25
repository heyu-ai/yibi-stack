---
name: pr-review-cycle
type: know
scope: global
description: >
  完整 PR 生命週期：從建立 PR 到 code-review → parallel review → fix → re-review → CI → merge → spectra archive + Jira sync。
  觸發情境：「跑 PR cycle」「review 這個 PR」「pr-review-cycle」「完整 PR 流程」「jira sync」「spectra archive」
---

# PR Review Cycle

Complete workflow from PR creation to merge, for any tech stack (Python / JS / Go / others).

## Usage

```text
/pr-review-cycle
/pr-review-cycle #<PR number>   ← skip to Step 2 if PR already exists
```

---

## Workflow

### Step 1 — Create PR

If no PR exists yet, run in order:

```bash
# Confirm you're on a feature branch, not main
git branch --show-current

# Commit all uncommitted changes
git add <files>
git commit -m "..."

# Push and create PR
git push -u origin HEAD
# Write PR body with Write tool to /tmp/pr-body.md, then pass it in (avoids hook intercepting markdown headers)
gh pr create --title "..." --body-file /tmp/pr-body.md
rm -f /tmp/pr-body.md
```

If the project has `/commit-commands:commit-push-pr` installed, run that directly (auto commit + push + PR).

Note the PR number for later steps.

---

### Step 1.5 — Scope Drift Detection (Informational, non-blocking)

After creating the PR, check: "Did it do what it should — not too much, not too little?"

```bash
git diff main...HEAD --stat
```

Also read the PR description (stated intent):

```bash
gh pr view --json title,body -q '"\(.title)\n\(.body)"'
```

Compare diff against stated intent, output:

```text
Scope Check: [CLEAN / DRIFT DETECTED / REQUIREMENTS MISSING]
Intent:    <1 sentence: what the PR claims to do>
Delivered: <1 sentence: what the diff actually changed>
[If DRIFT: list each change not in the plan]
[If MISSING: list requirements mentioned in PR description but absent from diff]
```

This step is **informational** and does not block the workflow. If DRIFT DETECTED, note it alongside the Step 3 code review results.

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
- **Has findings** → bring into Step 4 (Fix) and handle together with parallel review results.
  `/code-review` **does not modify code**; findings are review comments and do not need a separate commit.

> **Fallback (Claude Code < 2.1.146)**: if `/code-review` reports `Unknown skill: code-review`,
> use `pr-review-toolkit:code-reviewer` agent instead (same behavior — report only, no code changes):
>
> ```text
> Agent(subagent_type=pr-review-toolkit:code-reviewer,
>       prompt="Code review all diffs in this PR; report bugs / convention violations / logic errors")
> ```

---

### Step 3 — Parallel Review (launch 4 agents in parallel)

Launch all review agents (`pr-review-toolkit` subagents) **in the same message**:

| Agent | Focus |
|-------|-------|
| `code-reviewer` | Convention compliance, potential bugs, logic errors |
| `silent-failure-hunter` | Silent failures, swallowed exceptions, bad fallbacks |
| `pr-test-analyzer` | Test coverage gaps, untested critical paths |
| `comment-analyzer` | Documentation accuracy, comment rot, misleading descriptions |

Aggregate results, graded:

- **Critical** (blocks merge)
- **Important** (should fix)
- **Minor** (optional)

---

### Step 4 — Fix

Process **Critical** → **Important** in order:

1. Modify the code.

2. After each batch of fixes, run local CI. First read the project root to find the actual CI command:

   ```bash
   # Find CI entry point (check in order)
   cat Makefile 2>/dev/null | grep -E "^ci:|^test:|^check:" | head -5
   cat package.json 2>/dev/null | python3 -c "import json,sys; s=json.load(sys.stdin).get('scripts',{}); [print(k,':',v) for k,v in s.items() if k in ('test','ci','check')]"
   cat pyproject.toml 2>/dev/null | grep -A2 "\[tool.pytest\|testpaths"
   ```

   Common CI commands by stack:

   | Stack | Typical local CI command |
   |-------|--------------------------|
   | Python (make) | `make ci` |
   | Python (bare) | `uv run pytest` / `pytest` |
   | Node.js | `npm test` / `npm run ci` |
   | Go | `go test ./...` |
   | Rust | `cargo test` |

   If CI fails, **fix it before continuing** — do not skip.

3. Commit (message describes what was fixed, not "fix review comments"):

   ```bash
   git commit -m "fix(...): ..."
   git push
   ```

---

### Step 5 — Re-review

Re-run the Step 3 agents on **files modified in this round**:

```bash
git diff main...HEAD --name-only   # confirm scope
```

Confirm all Critical / Important issues are resolved. If new issues appear, return to Step 4.

---

### Step 6 — CI Check

Wait for GitHub Actions to pass:

```bash
gh pr checks {{pr_number}} --watch
```

If CI fails:

1. Reproduce locally first (using the local CI command found in Step 4).
2. Fix, commit, push.
3. Wait for CI again.

Local CI is authoritative: when CI and local results differ, trust local output and check for environment differences (Python version, env vars, cache, etc.).

---

### Step 7 — Merge

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
|-------------|----------------|
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

After CI is fully green, squash merge and capture the merge commit SHA (needed for Step 8b Jira comment):

```bash
gh pr merge {{pr_number}} --squash --delete-branch
```

```bash
gh pr view {{pr_number}} --json mergeCommit -q .mergeCommit.oid
```

Note the output SHA as `{{merge_commit_sha}}` and report it to the user.

---

### Step 8 — Spectra Archive + Jira Sync (wrap-up)

After the PR merges, sync spec state and Jira ticket to close the development cycle. Both sub-sections are **optional** — skip if no spectra change or no Jira issue.

#### 8a — Spectra Archive

If no spectra change was created for this dev cycle, skip Step 8a.

Otherwise, list in-progress changes and confirm whether one matches this PR (change name is usually close to the feature branch name):

```bash
spectra list
```

If the command fails, stop and report the error to the user; do not continue.

If a matching change is found, **report the change name to the user and wait for confirmation before archiving** (archive is irreversible):

> Found a likely matching spectra change: `{{change_name}}`. Confirm archive?

After confirmation:

```bash
spectra archive {{change_name}} --yes
```

If the command exits non-zero, stop and report the error. If validation has Critical errors,
run `spectra analyze {{change_name}}` to identify the issue, fix it, then archive again; only
use `--no-validate` if the user explicitly instructs it (the agent must not decide to skip
validation on its own).

---

#### 8b — Jira Sync

**Detect the Jira Issue Key**:

The branch was deleted by `--delete-branch`; extract the key from PR title / body instead:

```bash
gh pr view {{pr_number}} --json title,body -q '.title + " " + (.body // "")'
```

If the command itself exits non-zero, stop and report the error; ask the user to provide the key manually.
If the command succeeds but the output contains no string matching `[A-Z]{2,}-[0-9]+` (e.g. `ABC-123`), ask the user to provide the key or skip Step 8b.

**Get transitions (sequential), then run transition + comment in parallel**:

Call `mcp__claude_ai_Atlassian__getTransitionsForJiraIssue` (`issueId`: `{{jira_issue_key}}`) to get the transition list. If the call fails, stop and report the error.

Pick the option closest in meaning to "development complete and merged" (common options: `Done`, `Merged`, `Released`, `Closed`). If unsure, ask the user before proceeding.

After confirming the transition, the following two MCP calls **can be sent simultaneously** (no dependency); either failure must be reported and must not be silently ignored:

- `mcp__claude_ai_Atlassian__transitionJiraIssue`: move `{{jira_issue_key}}` to the selected state
- `mcp__claude_ai_Atlassian__addCommentToJiraIssue`: add a comment in this format:

```text
PR #{{pr_number}} squash-merged to main.
Merge commit: {{merge_commit_sha}}
```

If Step 8a archived a spectra change, append:

```text
Spectra change `{{change_name}}` archived; spec status updated to complete.
```

Report back to the user: spectra archive status (archived / skipped), Jira ticket status (transitioned to `{{selected_state}}` + comment written / skipped / failure reason).

---

## Troubleshooting

<!-- KEEP IN SYNC WITH ../pr-review-cycle-mob/SKILL.md (same FAQ row for pr-test-analyzer anti-patterns). If you update one, update both. -->

| Issue | How to handle |
|-------|---------------|
| How to avoid the three pr-test-analyzer traps (fake test / presence-only / no-CI)? | Three anti-patterns to always check: (1) **Fake test** (inverse of mutation testing) — the test case logic has a silent bug; all cases PASS but some test action never fires (e.g. env-var override test takes the unset branch; empty value not actually exported, so it runs the same path as another case); "all green" masks a scenario never tested. Fix: mutation testing intuition — intentionally break one production line and check whether that test case **really** fails; if not, it's a fake test. (2) **Presence test ≠ contract test** — `grep function_name` confirming the function is called is the weakest form; if the invariant is "the function must be called **with the correct args**" (e.g. the deploy script must call the guard helper with the **correct default context**), the test must verify the full contract (`function_name <expected_arg>` paired), not just function name presence. (3) **Test not wired to CI = half-finished test** — submitting a test file with no CI / pre-commit / git-hook / `make test` trigger means regressions are only caught when an operator manually runs tests; operators rarely do this spontaneously. Fix: "wired to CI?" should be listed alongside "what to test" and "how to test" as the three required test-design elements. Choose the mechanism per tech stack: Python repos use pre-commit local hook + `files:` regex; TS/JS use husky / lefthook; Go / Rust use `make test` + CI workflow `step: run: make test`. Common requirement: changing production code triggers tests automatically. |
| Step 3 agents have no git diff to read | Run Step 1 to create a branch/PR first |
| Cannot find local CI command | Read `Makefile` / `package.json` / `pyproject.toml`, or ask the user |
| Linter fails | Check the tool's `--fix` option (ruff: `ruff check --fix`; eslint: `--fix`; gofmt: auto-format) |
| Type checker fails | Check untyped third-party lib config (mypy: `follow_imports = skip`; tsc: add `@types/<pkg>` or set `skipLibCheck: true`) |
| Security scanner fails | Add the tool's ignore comment (bandit: `# nosec BXXX`), and explain the reason in the PR |
| Re-review finds new issues | Return to Step 4; do not merge directly |
| CI and local results differ | Trust local CI; compare tool versions and env vars between CI and local |
| Want to skip a review agent | Allowed, but explain the reason |
| spectra archive validation fails | Run `spectra analyze {{change_name}}` to view Critical errors, fix them, then archive; `--no-validate` requires explicit user instruction |
| Cannot detect Jira key from branch / PR | Ask the user to provide the key (format: `PROJECT-123`), or confirm this PR has no associated Jira issue and skip |
| Jira transition options unclear | Call `getTransitionsForJiraIssue` to list all options and ask the user to confirm |
| Jira MCP requires authentication | Atlassian MCP requires OAuth; if the tool returns an auth error, prompt the user to authorize on claude.ai |
| User skipped bump but needs a version tag later | Create a release branch, run [`/bump-version`](../bump-version/SKILL.md) on it, then open a PR to merge into main (CI pass + CHANGELOG confirmed is sufficient; no full review cycle needed; if main has new commits, CHANGELOG may include extra entries — verify manually) |
