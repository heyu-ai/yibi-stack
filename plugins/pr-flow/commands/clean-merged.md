---
description: Clean up all local git branches that have been merged (including squash/rebase merged branches with corresponding merged PRs)
model: sonnet
---
<!-- markdownlint-disable-file MD041 -->

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
   # split to avoid $(outer "$(inner)") -- Rule 14 Quoting Rule 4
   GIT_COMMON=$(git rev-parse --path-format=absolute --git-common-dir)
   MAIN_REPO=$(dirname "$GIT_COMMON")
   PM="uv run --project $MAIN_REPO python -m tasks.local_port_manager"

   # 對每個 PR 已 merged 的 branch 執行以下 loop：
   gh pr list --state merged --json headRefName -q '.[].headRefName' \
     | while read branch; do
       [ -z "$branch" ] && continue
       git show-ref --verify --quiet "refs/heads/$branch" || continue
       # Port 登記清理（有登記才 release；工具不可用時警告但繼續）
       if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
         echo "  [WARN] 不在 git repo 內 -- 跳過 port cleanup for $branch"
       elif command -v uv >/dev/null 2>&1 && [ -n "$MAIN_REPO" ]; then
         ports=$($PM list -p "$branch" 2>/dev/null | awk 'NR>2 {print $2}')
         if [ -n "$ports" ]; then
           echo "$ports" | while read svc; do
             $PM release "$branch" "$svc" \
               && echo "  [OK] released port: $branch/$svc" \
               || echo "  [FAIL] failed to release port: $branch/$svc (registry may need manual cleanup)"
           done
         fi
       else
         echo "  [WARN] uv 不可用 -- 跳過 port cleanup for $branch"
       fi
       # 刪除 branch
       git branch -D "$branch"
     done
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
