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
| `gh release create` | Publishes a package version; cannot be deleted (NPM 72h limit, PyPI permanent) | Confirm version, CHANGELOG, and tag; let user run |
| `npm publish` | Same as above | Run `npm pack` to inspect package contents first |
| `uv publish` | Same as above | Verify `dist/` contents and version first |

```bash
# Agent must not run autonomously:
kubectl apply -f k8s/prod/
terraform apply
gh release create v1.2.3
npm publish
uv publish
```

## Category 3: Git Destructive

| Operation | Risk | Recommended approach |
|-----------|------|----------------------|
| `git push --force` / `git push -f` | Overwrites remote commit history; affects all collaborators | Explain why force push is needed; let user run; confirm it is a personal branch |
| `git reset --hard <ref>` | Discards local uncommitted and committed changes | Run `git status` + `git log` to show scope; let user confirm |
| `git rebase` on a shared branch | Rewrites shared history; others must force-pull | Confirm whether branch is personal; use merge instead of rebase on shared branches |
| `git filter-branch` / `git filter-repo` | Rewrites entire repository history | Almost always requires explicit user authorization; describe and let user run |

```bash
# Agent must not run autonomously:
git push --force origin main
git push -f
git reset --hard HEAD~3
git filter-branch --env-filter '...'
```

**Exception**: `git reset --hard` on a personal worktree branch that affects only local un-pushed
changes has limited blast radius and may proceed after explanation.
Criterion: whether the branch has been pushed to remote.

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
| `rm -rf <path>` | Recursive delete; cannot recover from Trash | Run `ls <path>` to show contents; let user confirm; or use `trash` instead |
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

## Scope

This rule applies to all Claude Code agent sessions. It does not affect commands the user
runs directly in a terminal.
Doc-layer rule (v2): no `.claude/settings.json` deny-list entries; mechanical blocking planned for v3.
