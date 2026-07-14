#!/usr/bin/env bash
# handover-back.md Step 1 — 偵測 SKILL_REPO + 讀取交班記錄
# 用法：bash commands/scripts/handover-read.sh [--no-project]
#   --no-project：不帶 --project 過濾，顯示所有記錄（跨專案）
set -euo pipefail

if ! SKILL_REPO=$("$HOME/.agents/bin/resolve-skill-repo"); then echo '[FAIL] 無法解析 skill repo，請在 yibi-stack 目錄執行 make install' >&2; exit 1; fi

GIT_COMMON=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)
if [ -n "$GIT_COMMON" ]; then
  GIT_ROOT=$(dirname "$GIT_COMMON")
  PROJECT=$(basename "$GIT_ROOT")
else
  PWDVAL=$(pwd)
  PROJECT=$(basename "$PWDVAL")
fi

if [ "${1:-}" = "--no-project" ]; then
  uv run --directory "$SKILL_REPO" \
    python -m tasks.mycelium handover read --last 3 --exclude-tags pr-retrospective
else
  echo "PROJECT=$PROJECT"
  uv run --directory "$SKILL_REPO" \
    python -m tasks.mycelium handover read --last 3 \
    --project "$PROJECT" --exclude-tags pr-retrospective
fi
