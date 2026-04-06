#!/bin/bash
# PreToolUse hook: 阻止 worktree branch 推到 origin/main（或 origin/master）
# Claude Code pipes PreToolUse data as JSON to stdin:
#   {"tool_name": "Bash", "tool_input": {"command": "..."}}
#
# 問題根源：EnterWorktree / git worktree add 建立的 branch 預設追蹤 origin/main。
# 搭配 push.default=upstream，任何 git push 都會直推 main，繞過 PR 流程。
#
# 安裝方式：參考 skills/protect-push/SKILL.md

set -euo pipefail

# 讀取 stdin 一次（Claude Code 只傳送一次）
STDIN_DATA=$(cat)

# 從 JSON 解析 Bash command
# 只捕捉預期的解析錯誤（JSON 格式錯誤、型別問題），讓其他失敗觸發 || 警告
# 不加 2>/dev/null：Python 錯誤應可見，而非靜默消失
CMD=$(echo "$STDIN_DATA" | python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    print(data.get('tool_input', {}).get('command', ''))
except (json.JSONDecodeError, ValueError, KeyError, TypeError, AttributeError):
    print('')
") || {
    echo "protect-push: 警告：JSON 解析失敗，略過安全檢查" >&2
    exit 0
}

# 只攔截包含 git push 的指令
[[ "$CMD" != *"git push"* ]] && exit 0

# 取得目前 branch
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
[ -z "$BRANCH" ] && exit 0  # 非 git repo，放行

# main/master branch 本身推 main 是合法的
[ "$BRANCH" = "main" ] && exit 0
[ "$BRANCH" = "master" ] && exit 0

# 用 git config 查 upstream remote 與 merge ref
# 注意：不用 @{upstream} 語法，避開 zsh brace expansion 的靜默失效問題
REMOTE=$(git config "branch.${BRANCH}.remote" 2>/dev/null || echo "")
MERGE=$(git config "branch.${BRANCH}.merge" 2>/dev/null || echo "")

if [ "$REMOTE" = "origin" ] && [[ "$MERGE" =~ ^refs/heads/(main|master)$ ]]; then
    echo "BLOCKED: branch '${BRANCH}' 追蹤 origin/main！"
    echo "推送會直接到 main，繞過 PR 流程。"
    echo ""
    echo "請先修正 tracking 再 push："
    echo "  git branch --unset-upstream && git push -u origin HEAD"
    exit 2
fi

exit 0
