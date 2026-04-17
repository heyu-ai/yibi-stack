---
description: Clean up all local git branches that have been merged (including squash/rebase merged branches with corresponding merged PRs)
---

## Your Task

You need to clean up local git branches whose Pull Requests have been merged on GitHub. This includes branches merged via "Squash and merge" or "Rebase and merge" strategies.

## Commands to Execute

1. **Update local main branch**

   ```bash
   git checkout main && git pull origin main
   ```

2. **List all local branches and their corresponding PRs**

   ```bash
   # Get all non-main local branches
   git branch --format='%(refname:short)' | grep -v '^main$'

   # Get all merged PRs
   gh pr list --state merged --json number,headRefName,state,title --limit 100
   ```

3. **For each local branch, check if it has a merged PR**
   Compare branch names with PR headRefName. If a branch's PR is merged:
   - Delete the local branch

4. **Clean up process**

   ```bash
   # Delete the branch
   git branch -D <branch-name>
   ```

## Expected Behavior

After executing these commands, you will:

1. Show a summary of:
   - Branches with merged PRs (to be deleted)
   - Branches without PRs (need user confirmation)
   - Branches with open PRs (keep)

2. Delete all local branches whose PRs have been merged

3. Provide a clean summary of what was deleted

## Safety Checks

- ✅ Always update main branch first
- ✅ Only delete branches with merged PRs (MERGED state)
- ✅ Warn about branches without PRs before deleting
- ⚠️ Never delete main branch
- ⚠️ Keep branches with open PRs

## Notes

- This command works with GitHub's "Squash and merge" strategy
- It uses `gh pr list` to verify PR merge status
- Branches are only deleted if their PR is in MERGED state
