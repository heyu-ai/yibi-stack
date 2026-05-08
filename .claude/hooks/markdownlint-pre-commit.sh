#!/usr/bin/env bash
# 在 git commit 前自動對 staged .md 檔執行 markdownlint
set -euo pipefail

input=$(cat)
cmd=$(echo "$input" | jq -r '.tool_input.command // ""' 2>/dev/null || true)

# 只在 git commit 指令時觸發
if ! echo "$cmd" | grep -qE '^git commit'; then
  exit 0
fi

# effort=low 時跳過（快速迭代模式）。
# 注意：markdownlint 是唯一自動攔截 .md 格式違規的機制；low 模式下不合規的 .md 可被 commit。
# CLAUDE_EFFORT 值：low=跳過, 其他值（含預設 normal）=正常執行。
if [ "${CLAUDE_EFFORT:-normal}" = "low" ]; then
  echo "[SKIP] markdownlint 跳過（CLAUDE_EFFORT=low）" >&2
  exit 0
fi

staged=$(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null | grep '\.md$' || true)
if [ -z "$staged" ]; then
  exit 0
fi

echo "🔍 markdownlint 檢查 staged .md 檔..."
echo "$staged" | tr '\n' '\0' | xargs -0 npx markdownlint-cli2 2>&1
