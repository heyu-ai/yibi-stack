#!/usr/bin/env bash
# 在 git commit 前自動對 staged .md 檔執行 markdownlint
set -euo pipefail

input=$(cat)
cmd=$(echo "$input" | jq -r '.tool_input.command // ""')

# 只在 git commit 指令時觸發
if ! echo "$cmd" | grep -qE '^git commit'; then
  exit 0
fi

staged=$(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null | grep '\.md$' || true)
if [ -z "$staged" ]; then
  exit 0
fi

echo "🔍 markdownlint 檢查 staged .md 檔..."
echo "$staged" | tr '\n' '\0' | xargs -0 npx markdownlint-cli2 2>&1
