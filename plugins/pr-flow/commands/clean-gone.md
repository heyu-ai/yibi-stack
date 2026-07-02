---
description: Enhanced version - Clean branches marked as [gone] AND optionally all merged branches with PRs
model: sonnet
---
<!-- markdownlint-disable-file MD041 -->

## Your Task

Clean up stale local git branches. This command can:

1. Clean branches marked as [gone] (remote deleted)
2. Optionally clean ALL branches with merged PRs

## Commands to Execute

### Step 1: Check [gone] branches

```bash
echo "=== Checking [gone] branches ==="
git branch -v | grep '\[gone\]'
```

### Step 2: Check merged PRs

```bash
echo "=== Checking merged PRs ==="
# Get local branches
local_branches=$(git branch --format='%(refname:short)' | grep -v '^main$')

# Get merged PRs
gh pr list --state merged --json number,headRefName,state --limit 100
```

### Step 3: Ask user preference

Present options:

- `1`: Clean only [gone] branches (safe, remote already deleted)
- `2`: Clean [gone] branches + all merged PR branches (more thorough)
- `3`: Cancel

### Step 4: Execute cleanup based on choice

**Option 1: Clean [gone] branches only**

```bash
MAIN_REPO=$(git worktree list | head -1 | awk '{print $1}')
[ -z "$MAIN_REPO" ] && { echo "[FAIL] git worktree list 無法取得主 repo 路徑" >&2; exit 1; }

git branch -v | grep '\[gone\]' | sed 's/^[+* ]//' | awk '{print $1}' | while read branch; do
  echo "Processing branch: $branch"
  # Port 登記清理（有登記才 release；工具不可用時警告但繼續）
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "  [WARN] 不在 git repo 內 -- 跳過 port cleanup for $branch"
  elif command -v uv >/dev/null 2>&1 && [ -n "$MAIN_REPO" ]; then
    ports=$(uv run --directory "$MAIN_REPO" python -m tasks.local_port_manager list -p "$branch" 2>/dev/null | awk 'NR>2 {print $2}')
    if [ -n "$ports" ]; then
      echo "$ports" | while read svc; do
        uv run --directory "$MAIN_REPO" python -m tasks.local_port_manager release "$branch" "$svc" \
          && echo "  [OK] released port: $branch/$svc" \
          || echo "  [FAIL] failed to release port: $branch/$svc (registry may need manual cleanup)"
      done
    fi
  else
    echo "  [WARN] uv 不可用 -- 跳過 port cleanup for $branch"
  fi
  echo "  Deleting branch: $branch"
  git branch -D "$branch"
done
```

**Option 2: Clean [gone] + merged PR branches**

```bash
# First clean [gone] branches (same as option 1, port release included)
# Then clean merged PR branches (same as /clean-merged command, port release included)
```

## Expected Behavior

1. Show summary of:
   - Branches marked as [gone]
   - Branches with merged PRs
   - Total branches to be cleaned

2. Ask user for confirmation and cleanup strategy

3. Delete branches accordingly

4. Provide detailed cleanup report

## Safety Features

- ✅ Always show preview before deletion
- ✅ User confirmation required for option 2
- ✅ Separate handling for [gone] vs merged PR branches
- ✅ Never delete main branch
