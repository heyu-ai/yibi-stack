#!/bin/bash
# Step 2b: copy gitignored development files from main repo to worktree
set -euo pipefail

WT_LINE=$(git worktree list --porcelain | head -1)
MAIN_REPO=${WT_LINE#worktree }
if [ -z "$MAIN_REPO" ] || [ "$MAIN_REPO" = "$WT_LINE" ]; then
  echo '[FAIL] git worktree list --porcelain output has unexpected format' >&2
  exit 1
fi
WT=$(git rev-parse --show-toplevel)

for f in .env backend/.env frontend/.env admin/.env mobile/.env; do
  [ -f "$MAIN_REPO/$f" ] && cp "$MAIN_REPO/$f" "$WT/$f" && echo "  [OK] copied $f"
done

[ -d "$MAIN_REPO/.runtime" ] && cp -r "$MAIN_REPO/.runtime" "$WT/.runtime" && echo "  [OK] copied .runtime/"

if [ "$MAIN_REPO" = "$WT" ]; then
  echo "  [WARN] MAIN_REPO == WT, skipping settings.local.json copy" >&2
elif [ -f "$MAIN_REPO/.claude/settings.local.json" ]; then
  mkdir -p "$WT/.claude"
  cp "$MAIN_REPO/.claude/settings.local.json" "$WT/.claude/settings.local.json"
  echo "  [OK] copied .claude/settings.local.json"
fi
echo "[OK] Step 2b done"
