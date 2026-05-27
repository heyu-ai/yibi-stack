#!/bin/bash
# handover-back.md Step 1 — 偵測 SKILL_REPO + 讀取交班記錄
# 用法：bash commands/scripts/handover-read.sh [--no-project]
#   --no-project：不帶 --project 過濾，顯示所有記錄（跨專案）
set -euo pipefail

if ! SKILL_REPO=$(python3 -c 'import json,pathlib; print(json.loads((pathlib.Path.home()/".agents"/"config.json").read_text(encoding="utf-8")).get("skill_repo") or "")'); then
  echo '[FAIL] 讀取 ~/.agents/config.json 失敗' >&2; exit 1
fi
if [ -z "$SKILL_REPO" ]; then
  echo '[FAIL] skill_repo 未設定，請在 yibi-stack 目錄執行 make install' >&2; exit 1
fi
if [ ! -d "$SKILL_REPO" ]; then
  echo "[FAIL] skill_repo 路徑不存在或非目錄：$SKILL_REPO" >&2; exit 1
fi

GIT_COMMON=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)
if [ -n "$GIT_COMMON" ]; then
  PROJECT=$(basename "$(dirname "$GIT_COMMON")")
else
  PROJECT=$(basename "$(pwd)")
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
