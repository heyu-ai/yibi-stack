# Irreversible Operations

v2 doc-layer rule. The following operations **must not be executed autonomously by the agent** —
explain the operation, expected impact, and rollback difficulty first; let the user decide
whether to proceed or execute manually.

## Definition

An operation qualifies when it meets any of:

1. **Data unrecoverable**: data is permanently lost or overwritten with no quick restore from VCS or backup
2. **Cross-environment impact**: affects production, a remote repository, cloud resources, or external services
3. **Requires explicit authorization**: releasing a package version, deploying to production, modifying shared git history

## Agent Standard Behavior

```text
STOP: <operation description>
Impact: <which resources are affected and scope>
Rollback difficulty: <High / Medium / Low + explanation>
Recommendation: <dry-run command> or <ask user to run manually>
```

Do not execute in a bash call; describe in plain text and wait for user confirmation.

---

## Category 1: DB / Storage

| Operation | Risk | Recommended approach |
|-----------|------|----------------------|
| `alembic upgrade head` / `alembic downgrade` | Schema change is irreversible; downgrade may drop column data | Run `alembic check` first; let user execute after confirming |
| `prisma migrate deploy` | Applies production migration directly, no dry-run | Run `prisma migrate diff` to show SQL diff first |
| `flyway migrate` | Same as above | Run `flyway info` to confirm pending versions |
| `DROP TABLE` / `TRUNCATE` / `DELETE` without WHERE | Data permanently gone | Describe the SQL; ask user to run manually; confirm row count with `SELECT COUNT(*)` first |

```bash
# Agent must not run autonomously:
alembic upgrade head
prisma migrate deploy
psql -c "DROP TABLE users"
psql -c "DELETE FROM sessions"   # no WHERE clause
```

## Category 2: Deployment

| Operation | Risk | Recommended approach |
|-----------|------|----------------------|
| `kubectl apply` to prod namespace | Directly changes production workload | Run `kubectl diff` or verify in staging first; let user apply |
| `terraform apply` (any form, including `-target`) | Directly changes cloud infrastructure; `-target` can still delete or recreate resources | Run `terraform plan`; let user review before executing |
| `terraform destroy` / `pulumi destroy` / `cdk destroy` | Tears down provisioned infrastructure; data on destroyed resources is gone | Describe the stack and scope; let user run manually unless they named the specific stack |
| `gh release create` | Publishes a package version; cannot be deleted (NPM 72h limit, PyPI permanent) | Confirm version, CHANGELOG, and tag; let user run |
| `npm publish` | Same as above | Run `npm pack` to inspect package contents first |
| `uv publish` | Same as above | Verify `dist/` contents and version first |

```bash
# Agent must not run autonomously:
kubectl apply -f k8s/prod/
terraform apply
terraform destroy
pulumi destroy
cdk destroy
gh release create v1.2.3
npm publish
uv publish
```

**Native auto-mode interception (Claude Code v2.1.183+)**: auto mode now natively blocks
`terraform destroy` / `pulumi destroy` / `cdk destroy` unless you named the specific stack.
This is defense-in-depth on top of this doc-layer rule — see the note at the end of Category 3.

### Release Operations Must Not Run in a Shared Checkout Without a Fresh-State Check

`bump.sh` / `changelog.sh` / `git tag` / `git push origin <tag>` / `gh release create`
mutate the **main checkout directory directly** (not a PR branch) — they cannot run inside
an isolated worktree without producing a release on the wrong branch. But the main checkout
is also the one directory every concurrent session/user on the same machine shares. If two
release flows interleave in that directory — e.g. one session runs the individual
`bump-version` scripts step by step while another runs the full `make release` target — the
second flow's `bump.sh` silently reads the **first flow's already-written** version bump
(the file on disk, not the version you last checked), computes a further bump on top of it,
and commits a spurious, doubly-bumped `chore(release)` commit. The first flow may have
already tagged and pushed a real release by the time this happens — so the corrupted commit
sits, unpushed, on top of a real release with no error at any step.

```bash
# Wrong: assumes you are the only process touching the shared main checkout
(cd "$MAIN_REPO" && ~/.claude/skills/bump-version/scripts/bump.sh minor)
# ... proceeds straight to commit/tag without re-checking origin/main

# Correct: fetch and compare immediately before AND after any multi-step release flow
git -C "$MAIN_REPO" fetch origin main
git -C "$MAIN_REPO" rev-parse main origin/main   # must match before starting
# ... run bump/changelog/gates/commit ...
git -C "$MAIN_REPO" fetch origin main
git -C "$MAIN_REPO" log origin/main..main --oneline   # review before pushing/tagging
```

If the pre-push check shows more than the commit(s) you just made, another process already
completed a release — `git reset --hard origin/main` to discard your local-only commits
(safe: they were never pushed) rather than pushing on top of an already-completed release.
(Source: yibi-stack PR #210 retro — `bump.sh` read a `pyproject.toml` version that had
already been bumped moments earlier by a concurrent `make release` run in the same shared
main checkout, producing a phantom `v1.8.0` commit stacked on the real, already-tagged and
already-released `v1.7.0`.)

## Category 3: Git Destructive

| Operation | Risk | Recommended approach |
|-----------|------|----------------------|
| `git push --force` / `git push -f` | Overwrites remote commit history; affects all collaborators | Explain why force push is needed; let user run; confirm it is a personal branch |
| `git reset --hard <ref>` | Discards local uncommitted and committed changes | Run `git status` + `git log` to show scope; let user confirm |
| `git checkout -- .` / `git checkout -- <path>` | Discards uncommitted working-tree changes; not recoverable from VCS | Run `git status` to show what would be lost; let user confirm |
| `git clean -fd` | Permanently deletes untracked files and directories (no Trash) | Run `git clean -nd` (dry-run) to list affected paths first; let user confirm |
| `git stash drop` / `git stash clear` | Discards stashed changes; not in commit history | Run `git stash list` + `git stash show -p` to show scope; let user confirm |
| `git commit --amend` (commit not authored by the agent this session) | Rewrites an existing commit's content/message; loses the original | Confirm the commit is yours to amend; otherwise create a new commit instead |
| `git rebase` on a shared branch | Rewrites shared history; others must force-pull | Confirm whether branch is personal; use merge instead of rebase on shared branches |
| `git filter-branch` / `git filter-repo` | Rewrites entire repository history | Almost always requires explicit user authorization; describe and let user run |

```bash
# Agent must not run autonomously:
git push --force origin main
git push -f
git reset --hard HEAD~3
git checkout -- .
git clean -fd
git stash drop
git stash clear
git commit --amend          # when the target commit was not authored by the agent this session
git filter-branch --env-filter '...'
```

**Exception**: `git reset --hard` on a personal worktree branch that affects only local un-pushed
changes has limited blast radius and may proceed after explanation.
Criterion: whether the branch has been pushed to remote.

### Defense in Depth: Native Auto-Mode Interception (v2.1.183+)

Claude Code v2.1.183+ auto mode now **natively intercepts** these destructive commands unless
you explicitly request them: `git reset --hard`, `git checkout -- .`, `git clean -fd`,
`git stash drop`, `git commit --amend` (when the commit was not authored by the agent this
session), and `terraform/pulumi/cdk destroy` (unless the specific stack is named).

This is a runtime safety net layered **on top of** this doc-layer rule, not a replacement:

- **This rule remains the primary line of defense.** It applies in every permission mode (not
  only auto mode), defines the STOP/Impact/Rollback reporting format, and lists operations the
  native interceptor does not cover (e.g. `find ... -delete`, `aws s3 rm --recursive`).
- **Do not relax doc-layer judgment because "auto mode will block it."** The native list is
  fixed and version-dependent; an operation outside it (or a user on an older version, or a
  non-auto mode) gets no native guard. Always apply the Agent Standard Behavior above first.

### Prevention: Verify the Current Branch Before the Session's First Commit

`git commit` targets whatever branch the working tree happens to be on — which is not
necessarily where *this* session started. A previous session, or a background job, can leave the
shared checkout parked on an unrelated branch, and the first commit of the new session silently
stacks onto it.

```bash
# Run this before EVERY commit -- the first most of all, but re-check any later commit too if a
# background job may have moved the shared checkout in the meantime
git -C <repo> branch --show-current
```

If the answer is not the branch you intend, stop and fix it **before** committing; the recovery
below is strictly harder than the check.

**The dominant culprit is `nightly-agent/YYYY-MM-DD/*`.** The nightly self-improvement agent
creates and checks out a branch per friction inside the shared main checkout, and does not
restore the previous branch when its run aborts partway. Any session that starts afterward
inherits that branch. This is observed, not hypothetical: incident #269 landed a proposal commit
on a nightly-agent branch exactly this way. The specific branch a checkout is parked on is
ephemeral — it varies by day and is often gone by the time you read this — so the durable evidence
is that merged incident, not any one transient ref.

Checking at commit time is what matters — checking at session start is not equivalent, because a
concurrently running background job can move the shared checkout mid-session. A background job that
will commit should isolate itself in its own worktree (so a concurrent checkout switch cannot
redirect its commits at all); absent that, re-run the check immediately before *each* commit, not
just the first.

### Recovery: Rescuing a Commit Accidentally Made on Main (Only if Not Yet Pushed)

When a commit was made directly on `main` and needs to become a PR, the situation is fully
reversible **before pushing**. Order matters:

```bash
# 1) Save the commit with a branch ref first (branch is a lightweight ref; no data loss)
git branch <feat-name> HEAD

# 2) Reset main back to origin/main (safe here because the commit is preserved by step 1)
git reset --hard origin/main

# 3) Switch to the saved feat branch and push as a PR
git checkout <feat-name>
git push -u origin <feat-name>
```

**Why order cannot be reversed**: `reset --hard` first then `branch` loses the commit (HEAD
has already moved back; the new branch just points to origin/main). `branch` first then `reset`
is atomic defense: step 1 success = commit can never be lost, step 2 failure is harmless.

**Pre-flight canary (strongly recommended before step 2)**:

```bash
# Fetch to get latest remote view; then list commits ahead of origin/main
git -C <repo> fetch origin
git -C <repo> log HEAD..origin/main --oneline   # should be empty (origin has no new commits)
git -C <repo> log origin/main..HEAD --oneline   # should show only the commit you want to save
```

If `origin/main..HEAD` shows more commits than expected, or includes commits already in
`origin/main`, **stop** — main may not be in the state you assume. Better to miss the recovery
than to accidentally delete work. Confirm the single target commit before running step 2.

**Criterion**: before step 2, confirm `git push` has never been run (`git log origin/main..main`
shows the target commit and that commit is absent from `origin/main` history).
If already pushed, this recovery does not apply — use PR + revert commit workflow instead.

## Category 4: File Destructive

| Operation | Risk | Recommended approach |
|-----------|------|----------------------|
| `rm -rf <path>` | Recursive delete; cannot recover from Trash | **The only reliable rule is: do not delete a directory whose work is not committed.** The probes below narrow the risk in common cases; they do **not** prove safety (see "What the probes do not tell you"). Run all four with `git -C <path>` so they hit the index that owns `<path>` — and `<path>` must be **inside** the owning worktree, never a parent of one: `git -C <path> status --porcelain .`, `git -C <path> ls-files`, `git -C <path> clean -ndx .` (`-x` required, or gitignored files are silently omitted), `find <path> -name .git` (nested repos/worktrees, which `clean` skips — silently when `<path>` is tracked). Let user confirm; or use `trash` instead |
| `find ... -delete` | Batch delete; scope is hard to predict | Run `find ... -print` (without `-delete`) to show affected files first |
| `> file` overwriting an existing file | Original content permanently gone | Confirm whether backup or git version exists; use `>>` append instead, or `cp` first |
| `truncate -s 0 file` | Empties file content | Confirm file purpose; describe and let user confirm |

```bash
# Agent must not run autonomously:
rm -rf /path/to/dir
find /path -name "*.log" -delete
> /etc/config.json           # overwrites an existing config file
truncate -s 0 data/prod.db
```

### `rm -rf` Safety: Status Is Not a Safety Check

`git status --porcelain` lists files with **changes**, not all tracked files. A clean status
does NOT mean safe to delete — unmodified tracked files are invisible.

**The only reliable rule: do not delete a directory whose work is not committed.**

Before `rm -rf`, run four probes (none alone is sufficient):

1. `git -C <path> status --porcelain .` — uncommitted changes
2. `git -C <path> ls-files` — tracked files (use `-C <path>`, not `git ls-files -- <path>` — the latter silently returns empty for worktree paths)
3. `git -C <path> clean -ndx .` — unrecoverable untracked+gitignored files (`-x` required, or gitignored files are silently omitted)
4. `find <path> -name .git` — nested repos/worktrees (`clean` silently skips these)

```bash
# Wrong: status shows clean, assumed safe to delete
git status --porcelain dir/   # tracked, unmodified .gitkeep is invisible
rm -rf dir/                   # deletes tracked content

# Fix: check what git tracks
git -C dir/ ls-files          # shows the .gitkeep
```

Recovery: `git checkout HEAD -- <path>` (not bare `checkout --`, which reads the index and
fails when a concurrent session staged the deletion). `-C` the worktree root, not the deleted
path — you can't `-C` into what's gone. Caveat: `checkout HEAD --` is the more reliable
command, not the lossless one — it fails rc=1 for staged-add files (`A` in status) and silently
overwrites staged edits with HEAD's version. Prefer not deleting over choosing a recovery command.

Probes have blind spots: `assume-unchanged` / `skip-worktree` files pass all four probes as
"clean" while holding unrecoverable local edits (`ls-files -v` reveals the `h`/`S` flag).
The probes narrow risk in ordinary cases — the rule at the top is the backstop.

### Boolean Safety Gates Must Be Tri-State

A safety-check returning `bool` collapses "probe failed" into one of the two real answers.
Use `bool | None` — treat `None` as the conservative branch.

```python
# Wrong: probe failure and "confirmed unused" both return False
def is_still_in_use(path: Path) -> bool:
    result = subprocess.run(["some-tool", "list"], ...)
    if result.returncode != 0:
        return False          # probe failed, NOT "confirmed unused"
    return path in parse(result.stdout)

# Fix: None = couldn't check → skip the destructive action
def is_still_in_use(path: Path) -> bool | None:
    """True = in use; False = confirmed free; None = probe failed."""
    result = subprocess.run(["some-tool", "list"], ...)
    if result.returncode != 0:
        return None
    return path in parse(result.stdout)

if is_still_in_use(target) is False:  # only confirmed-safe takes the delete path
    shutil.rmtree(target)
```

## Category 5: Cloud

| Operation | Risk | Recommended approach |
|-----------|------|----------------------|
| `aws s3 rm --recursive s3://bucket/` | Bulk permanent object deletion; no recycle bin | Run `aws s3 ls --recursive` to confirm scope; let user confirm |
| `gcloud compute instances delete` | VM deletion destroys disk data (by default) | Confirm instance name and zone; let user run manually |
| `gcloud sql instances delete` | Database deleted; restoration takes time even with backups | Almost always let user run manually |
| `az group delete --resource-group` | Deletes entire Azure resource group and all resources within | Describe impact scope; let user run manually |

```bash
# Agent must not run autonomously:
aws s3 rm --recursive s3://prod-data/
gcloud compute instances delete my-vm --zone us-central1-a
gcloud sql instances delete prod-db
```

## Confirm Upstream Tracking Before `git push` (Prevent Accidental Push to Main)

A feature branch created from `origin/main` defaults to tracking `origin/main`.
Running `git push origin <feature-branch>` without `-u` pushes to `origin/main`
per the tracking config, bypassing PR review.

**Standard practice: run `git branch -vv` before pushing to verify upstream**

| Upstream shows | Push command |
|---------------|--------------|
| `[origin/main: ahead N]` | Must use `git push -u origin <branch-name>` to create a dedicated remote branch |
| `[origin/<branch-name>]` | Plain `git push` is fine |

```bash
# Verify upstream, then create remote branch with -u
git branch -vv
git push -u origin chore/my-feature-branch
```

This is an irreversible operation affecting a shared branch: once pushed to `origin/main`,
every collaborator's next `git pull` picks up unreviewed changes.
Personal worktree branches that have not been pushed are out of scope.

## Revert PR Pre-merge Checklist

When creating a revert PR (to undo commits that landed on a shared branch):

1. **Fetch and rebase onto latest `origin/main` before requesting review**:

   ```bash
   git fetch origin
   git rebase origin/main
   ```

2. **Verify diff scope matches stated intent**:

   ```bash
   git diff origin/main HEAD --name-only
   ```

   Should list only the files the revert commit actually touches.
3. **Why**: `origin/main` may have advanced since the revert branch was created
   (e.g., a security fix landed independently). Without rebase, the stale branch
   base causes `git diff origin/main HEAD` to include those newer commits in the
   diff — merging silently reverts them.

**Real incident (PR #55)**: After the revert branch was created, `5725b86`
(`security(agy): replace --dangerously-skip-permissions with --sandbox`) landed
on `origin/main`. Without rebase, the diff included 3 agy scripts. Mob review
caught it; rebase onto `origin/main` fixed the scope back to exactly 6 rule files.

## Worktree Path Resolution: `--show-toplevel` vs `--git-common-dir`

Inside a linked worktree (e.g., `.claude/worktrees/<name>/`), `git rev-parse --show-toplevel`
returns the **worktree's own directory**, not the main repo root.

```bash
# Wrong: inside a linked worktree, this returns .claude/worktrees/feat+.../
git rev-parse --show-toplevel

# Correct: get the main repo root from any location (worktree or main)
GIT_COMMON=$(git rev-parse --path-format=absolute --git-common-dir)
MAIN_REPO=$(dirname "$GIT_COMMON")
```

Applies to: any script that computes project slug, log path, transcript directory, or any path
that depends on the main repo root — when the script may run inside a linked worktree.

### `${CLAUDE_PROJECT_DIR}` Is the Session's Start Dir — Registering a Hook From a Worktree Can Brick the Session

Same axis, one layer up: `${CLAUDE_PROJECT_DIR}` is the project root **where the session
started**. It does not follow you into a worktree. Enter one mid-session (the normal flow: start
in the main repo, then `EnterWorktree`) and it stays pinned at the main repo — while the
**worktree's** `settings.json` is still the file that gets loaded.

That asymmetry is the trap. Registering a new hook there is live the moment you save it, but
`${CLAUDE_PROJECT_DIR}/.claude/hooks/<new>.py` resolves into the **main repo**, where your
unmerged script does not exist. Every subsequent Bash call dies with `can't open file ...` +
`exit 2` — including the calls you would use to undo it. Existing hooks keep working only
because the main repo already has their scripts.

**Recovery**: delete the registration block with the **Edit tool** — do not go looking for a Bash
escape, there isn't one.

Why Edit still works, stated as the invariant rather than the outcome: every **`PreToolUse`** hook
in this repo matches `Bash` or `Bash|EnterWorktree`. The two `Edit|Write` matchers you will find in
`settings.json` are **`PostToolUse`** — they run *after* the tool and cannot gate it. So the escape
is incidental, not structural: **register a `PreToolUse` hook on `Edit|Write` from a worktree —
exactly the sort of guard this rule corpus invites — and the Edit escape is gone too.** Recover
from outside the session then. Re-check the matchers before relying on this.

Not affected: a session launched *directly inside* the worktree, where `CLAUDE_PROJECT_DIR`
is the worktree itself.

**The workflow this implies.** Note what "live immediately" and "starts working after merge" mean
together: the registration fires from the moment you save it — it just fails, because the script
it points at is not in the main repo yet. There is no quiet window.

1. Develop and test the script in the worktree by invoking it directly, never via registration:
   `echo '<payload>' | python3 .claude/hooks/<new>.py; echo $?`
2. Write and commit the `settings.json` registration **last**. Saving it bricks this session's
   Bash calls — that is the trap above, not a way around it. Use the Edit-tool escape if you need
   to keep working, or do this step from a session you are willing to end.
3. Expect it to start **working** (not merely firing) after merge, once the script reaches the
   main repo.

(PR #214 retro: registering `protect-tracked-rm.py` from a worktree blocked every Bash call in
that session — twice, the second time after having just written this down.)

## A Linked Worktree Must Never Check Out `main`

Git lets exactly one worktree hold a given branch. If a linked worktree checks out `main`, the
main repo can no longer `git checkout main`, and every command that internally does so —
`gh pr merge`, `/clean-merged`, `/clean-gone` — fails with
`fatal: 'main' is already used by worktree at '...'`.

```bash
# Wrong: occupies the main ref for as long as the worktree exists
git worktree add .claude/worktrees/<name> main

# Correct: always branch off main
git worktree add .claude/worktrees/<name> -b <feat-branch> origin/main
```

`.claude/hooks/protect-worktree.py` enforces this at `PreToolUse`. That hook is the mechanism —
**this section is the reason**, recorded at the doc layer so the invariant survives the hook being
disabled, bypassed, or not yet installed in a fresh clone. `CLAUDE.md` lists `protect-worktree`
among the installed hooks without saying what it protects against; that list is not a substitute
for the invariant.

## `gh pr merge` From a Worktree: Non-Zero Exit Does Not Mean the Merge Failed

Related to the previous section but a **distinct and more dangerous** failure, because the
misleading signal points the wrong way: it reports failure for an operation that already
succeeded.

`gh pr merge` does two things in order:

1. **Merges the PR through the GitHub API** — remote-side, succeeds immediately
2. **Cleans up locally** — checks out the base branch, deletes the merged branch. This step only
   runs with `--delete-branch` (and depends on checkout state); a plain `gh pr merge` skips it. This
   repo's flow always passes `--delete-branch` (see the pr-cycle skills), so the failure below is
   the normal case here, not an edge case.

Run from inside a linked worktree, step 1 succeeds and step 2 fails with
`fatal: 'main' is already used by worktree`. The command exits non-zero and prints a worktree
error, so it reads as "the merge did not happen" — **but the PR is already merged.** Retrying
then produces confusing follow-on errors against an already-merged PR.

In this repo the **agent cannot run `gh pr merge`** — `protect-push` blocks it, so the user runs
it (see `CLAUDE.md`). Whoever ran it, after a non-zero exit establish the real outcome before
reacting; the checks below are read-only and safe for the agent to run:

```bash
# After ANY `gh pr merge` that exits non-zero, establish the real outcome before reacting
git -C <main-repo> fetch origin
git -C <main-repo> log origin/main -1 --oneline    # did the squash commit land?
gh pr view <N> --json state,mergedAt              # authoritative: MERGED or not
```

Never judge success or failure from that stderr alone. This is the same class as the exit-code
false-greens in [`13-bash-anti-patterns.md`](13-bash-anti-patterns.md) — *ask whose exit code you
just read* — except here the false signal is a false **negative**.

Prevention remains the rule in `CLAUDE.md`: run `gh pr merge` from the main repo directory.

## Post-Merge Branch Cleanup: `branch -d` Refuses, and Push-Without-PR Leaves Orphans

Two branch-lifecycle hazards that surface *after* a merge. Both end in an irreversible
`git branch -D` or `git push origin --delete`, so they belong in this rule.

### A squash-merged branch fails `git branch -d` — free the worktree first, then `-D`

A squash merge lands the branch's work as **one new commit on the base**, which does not carry
the feature branch's own commits as ancestors. So `git branch -d <branch>` — the *safe* delete
that refuses unless the branch is merged — reports `error: the branch '<branch>' is not fully
merged` even though the PR is merged, and `--delete-branch` has already removed the remote branch.

A **second** refusal stacks on top when the branch lived in a linked worktree: while that
worktree entry still exists, *any* delete (`-d` or `-D`) fails with `cannot delete branch
'<branch>' used by worktree at '...'`. So free the worktree **before** deleting the branch — the
order matters:

```bash
# From the MAIN repo root, after confirming the merge (gh pr view <N> --json state,mergedAt):
git worktree remove .claude/worktrees/<name>   # frees the branch; use `git worktree prune` if the dir is already gone
git branch -D <branch>                          # now unbound; -d still refuses post-squash, so -D force-deletes
```

`-D` is a force delete, but nothing is lost here: the squash commit on `origin/main` is the
canonical copy of the merged work. (A branch deleted *before* its work reached `origin/main` is a
different case — then it is recoverable only via the reflog / `git fsck --lost-found`, and only
before GC.)

### Push-without-PR leaves orphan `origin` branches that collide with later sessions

An automated session (e.g. the nightly self-improvement agent) that pushes `nightly-agent/*`
branches to `origin` but aborts before `gh pr create` leaves those branches on the remote with no
PR. They accumulate and later sessions hit branch-name collisions. Cleaning them up is an
irreversible, cross-environment remote deletion (Category 3), so audit and confirm scope first:

```bash
git ls-remote --heads origin 'nightly-agent/*'      # audit: list the orphan branches
git push origin --delete <branch> [<branch> ...]    # irreversible: the remote ref is gone
```

Never delete a branch whose only copy of some content is that branch. Before deleting, confirm
each branch's content is already on `main` (merged, or harvested into a rule) — the agent must
list the exact branches and get explicit confirmation before running `git push origin --delete`.

## Scope

This rule applies to all Claude Code agent sessions. It does not affect commands the user
runs directly in a terminal.
Doc-layer rule (v2): no `.claude/settings.json` deny-list entries for most categories above;
mechanical blocking for those remains planned for v3. The Category 4 `rm -rf`-against-tracked-content
case is the one exception — `.claude/hooks/protect-tracked-rm.py` (a `PreToolUse` hook, not a
deny-list entry) mechanically blocks the common forms of it as of #238's redo, including through
common wrappers (`env`/`sudo`/`timeout`/`xargs`/`exec`/...), grouping, cwd-changing options, and
git pathspec-magic filenames — see the hook's own module docstring "Known limitations" section for
what remains out of scope (deliberate obfuscation via `eval`/aliases/functions, indirect deletion
via external scripts, and the inherent TOCTOU window between probing and execution).
