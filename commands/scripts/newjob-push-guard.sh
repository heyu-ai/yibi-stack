#!/bin/bash
# Step 2a: verify worktree push tracking is set to the feature branch, not origin/main
set -euo pipefail

WT=$(git rev-parse --show-toplevel)
if [ -z "$WT" ]; then
  echo '[FAIL] git rev-parse --show-toplevel failed' >&2
  exit 1
fi

if [ -d "$WT/.git" ]; then
  echo '[FAIL] cwd is still in main repo -- EnterWorktree contract broken' >&2
  exit 1
fi

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ -z "$CURRENT_BRANCH" ]; then
  echo '[FAIL] cannot determine current branch name' >&2
  exit 1
fi
if [ "$CURRENT_BRANCH" = "HEAD" ]; then
  echo '[FAIL] worktree is in detached HEAD state -- run: git checkout <branch>' >&2
  exit 1
fi
if [ "$CURRENT_BRANCH" = "main" ]; then
  echo '[FAIL] worktree is checking out main -- delete this worktree and re-run /newjob' >&2
  exit 1
fi

UPSTREAM=$(git rev-parse --abbrev-ref 'HEAD@{upstream}' 2>/dev/null || true)
if [ -z "$UPSTREAM" ]; then
  UPSTREAM="none"
fi

if [ "$UPSTREAM" = "origin/main" ]; then
  echo "[WARN] DANGER: branch tracking origin/main, fixing..."
  git branch --unset-upstream
  git push origin "HEAD:$CURRENT_BRANCH"
  git branch -u "origin/$CURRENT_BRANCH"
  echo "[OK] fixed -- now tracking origin/$CURRENT_BRANCH"
else
  echo "[OK] Push tracking OK: $UPSTREAM"
fi
