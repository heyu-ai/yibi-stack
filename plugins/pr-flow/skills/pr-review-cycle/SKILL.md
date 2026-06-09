---
name: pr-review-cycle
type: know
scope: global
description: >
  完整 PR 生命週期（通用版，任何專案皆可用）：從建立 PR 到 code-review → parallel review（4 個 pr-review-toolkit subagent）
  → fix → re-review → CI → merge。無 SDD/spectra 依賴。
  SDD 專案（需要 spectra archive + Jira sync + amplifier-verifier）請改用 /pr-cycle-deep。
  觸發情境：「跑 PR cycle」「review 這個 PR」「pr-review-cycle」「完整 PR 流程」「parallel review」
---

# PR Review Cycle

Complete workflow from PR creation to merge, for any tech stack (Python / JS / Go / others).

## Usage

```text
/pr-review-cycle
/pr-review-cycle #<PR number>   ← skip to Step 2 if PR already exists
```

---

## Review Severity Standard (RFC 2119)

This is the **canonical** grading standard for every PR review finding — in this skill and in
`/pr-cycle-deep`. It applies regardless of source: `/code-review`, the four
`pr-review-toolkit` subagents, or external mob voices (Codex / Gemini). The grade a finding
receives is what decides its merge consequence.

Strength keywords follow [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119): **MUST** / **MUST
NOT** are absolute requirements; **SHOULD** / **SHOULD NOT** may be deviated from only with a
documented reason; **MAY** is genuinely optional. Grade by *merge consequence*, not by how bad
a finding subjectively feels.

| RFC 2119 | Grade | Merge consequence | What belongs here |
|----------|-------|-------------------|-------------------|
| **MUST** fix | **Critical** | Blocks merge — cannot merge until fixed | Functional / logic errors; security vulnerabilities (injection, auth bypass); secret or PII exposure in logs; data loss or corruption; violation of an explicit team baseline (a rule in `.claude/rules/`, a CLAUDE.md hard constraint, or a documented spec) |
| **SHOULD** fix | **Important** | Does not hard-block, but if deferred the author MUST record the reason in the PR description | Test coverage gaps on changed critical paths; maintainability defects (silent failures, swallowed exceptions, unsafe fallbacks); team-consistency violations (naming, module structure); documentation / comment rot that misleads readers |
| **MAY** fix | **Actionable NIT** | Does not block merge — fix opportunistically | Concrete, low-risk cleanup with an objective fix: naming alignment, typo / comment spelling, import order, small documentation clarification; never subjective preference or a vague needs-more-context concern |

### Per-category checklist

Concrete checks to run while reviewing; the strength keyword fixes each finding's grade.

#### Security & data protection

- Logs and error messages **MUST NOT** contain PII or secrets (tokens, passwords, keys).
- External input **MUST** be validated before use.
- Existing permission / authorization checks **MUST** be preserved.

#### Testing

- New error / failure branches **SHOULD** be covered by a test.
- Critical flows (payment, auth, migration) **SHOULD** have the happy path and at least one
  failure path tested.
- Each new conditional branch **SHOULD** have a corresponding case.

#### Code quality

- Code **SHOULD** use idiomatic language / framework features rather than reinventing them.
- Naming **SHOULD** stay consistent with the surrounding module.
- Code that intentionally keeps a legacy or non-obvious approach **SHOULD** document the
  rationale in a comment.

### Not a finding (discard)

The following are **never** raised — they are noise, not signal:

- Subjective preference with no objectively verifiable reason ("I find X more elegant than Y").
- Behaviour that is correct and tested but stylistically different from the reviewer's habit.
- A vague concern with no concrete, actionable fix.
- Design trade-offs with no objectively correct answer and no local consistency rule.

### Human-in-the-loop

Automated reviewers (`/code-review`, subagents, mob voices) **MAY** grade findings and propose
fixes, but they **MUST NOT** make the final call on a **Disputed** or **MAY**-level item — the
human author / reviewer decides. AI assists; it does not decide for the team.

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
# Multi-line message: write to $CLAUDE_JOB_DIR/commit_msg.txt with Write tool, then git commit -F

# Push and create PR
git push -u origin HEAD
# Write PR body with Write tool to /tmp/pr-body.md, then pass it in (avoids hook intercepting markdown headers)
gh pr create --title "..." --body-file /tmp/pr-body.md
rm -f /tmp/pr-body.md
```

If the project has `/commit-commands:commit-push-pr` installed, run that directly (auto commit + push + PR).

Note the PR number as `{{pr_number}}` for later steps.

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

### Step 1.6 — Parallel Pre-review Check (3 agents, same message)

> Unlike Step 1.5, this step is **blocking** — do not proceed to Step 2 if any agent fails or returns no usable output.

Spawn three Task agents **in a single message** to gather baseline information in parallel:

| Agent | Task |
|-------|------|
| **diff-reviewer** | Run `gh pr diff {{pr_number}}`; summarise changed files and line counts. **Do not use local `main`** — always fetch from GitHub. If the command exits non-zero, report `[FAIL] gh pr diff: <exact error>` and stop. |
| **ci-checker** | Run `gh pr checks {{pr_number}}`; report pass / fail / pending per check. If the list is empty, report "CI: not yet triggered". If the command exits non-zero, report `[FAIL] gh pr checks: <exact error>` and stop. |

If any agent reports `[FAIL]`, stop and report the failure explicitly; do not proceed to Step 2.

Once both return successfully, report the pre-review summary inline:

```text
Pre-review Check
- Diff: <file count> files, <line count> lines changed
- CI: <pass / fail / pending / not yet triggered — list any failing checks by name>
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

Aggregate results and grade each finding per the
[Review Severity Standard](#review-severity-standard-rfc-2119):

- **Critical** — MUST fix; blocks merge
- **Important** — SHOULD fix; defer only with a documented reason in the PR description
- **Actionable NIT** — MAY fix; optional

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

## Troubleshooting

<!-- KEEP IN SYNC WITH ../pr-cycle-deep/SKILL.md (same FAQ row for pr-test-analyzer anti-patterns). If you update one, update both. -->

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
| SDD project needs spectra archive + Jira sync | Use `/pr-cycle-deep` instead, which includes post-merge spectra archive and Jira sync steps |
| User skipped bump but needs a version tag later | Create a release branch, run [`/bump-version`](../bump-version/SKILL.md) on it, then open a PR to merge into main (CI pass + CHANGELOG confirmed is sufficient; no full review cycle needed; if main has new commits, CHANGELOG may include extra entries — verify manually) |
