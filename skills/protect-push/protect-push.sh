#!/bin/bash
# PreToolUse hook: 阻止 worktree branch 推到 origin/main（或 origin/master）
# Claude Code pipes PreToolUse data as JSON to stdin:
#   {"tool_name": "Bash", "tool_input": {"command": "..."}}
#
# 問題根源：EnterWorktree / git worktree add 建立的 branch 預設追蹤 origin/main。
# 搭配 push.default=upstream，任何 git push 都會直推 main，繞過 PR 流程。
#
# 覆蓋案例：
# 1. git -C <worktree-path> push ... — 解析 -C 路徑，檢查該 worktree 的 branch
# 2. WT=... && git -C "$WT" push ... — 解析 shell variable 後同上
# 3. git push (bare) — 檢查 CWD 的 branch tracking
#
# 安裝方式：參考 skills/protect-push/SKILL.md

set -euo pipefail

_DIR=$(dirname "${BASH_SOURCE[0]}")
SCRIPT_DIR=$(cd "$_DIR" && pwd)

STDIN_DATA=$(cat)

CMD=$(python3 -c '
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get("tool_input", {}).get("command", ""))
except (json.JSONDecodeError, ValueError, KeyError, TypeError, AttributeError):
    print("")
' <<< "$STDIN_DATA") || {
    echo "protect-push: 警告：JSON 解析失敗，略過安全檢查" >&2
    exit 0
}

# 只攔截包含 git push 的指令
[[ "$CMD" != *"git push"* && "$CMD" != *"git -C"*"push"* ]] && exit 0

block_push() {
    printf '%b\n' "$1"
    exit 2
}

# 確認 parse_git_dir.py 存在（有 -C 的 push 才強制要求）
if [[ ! -f "$SCRIPT_DIR/parse_git_dir.py" && "$CMD" == *"git -C"*"push"* ]]; then
    block_push "BLOCKED: protect-push: parse_git_dir.py 未安裝於 $SCRIPT_DIR\n請重新執行 make install-one SKILL=protect-push 更新安裝。"
fi

# 解析 git -C 路徑（支援 \$VAR 和 literal path，失敗時 exit 2 表示無法解析）
PARSE_EXIT=0
GIT_DIR=$(python3 "$SCRIPT_DIR/parse_git_dir.py" "$CMD" 2>/dev/null) || PARSE_EXIT=$?
if [ "$PARSE_EXIT" -ne 0 ]; then
    block_push "BLOCKED: protect-push: git -C target 無法解析（exit $PARSE_EXIT）\n請改用 literal path 或先把 worktree 路徑指定給變數再執行 push。"
fi

# 包裝 git 指令，依據是否有 GIT_DIR 決定是否加 -C
git_cmd() {
    if [[ -n "$GIT_DIR" ]]; then
        git -C "$GIT_DIR" "$@"
    else
        git "$@"
    fi
}

# 取得目前 branch
BRANCH=$(git_cmd rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
[ -z "$BRANCH" ] && exit 0

# main/master branch 直接 push 也應該擋住（這是 worktree 忘記切 branch 的情況）
if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
    block_push "BLOCKED: 目前在 '$BRANCH' branch！\n直接 push 到 $BRANCH 會繞過 PR 流程。\n\n請先建立 feature branch：\n  git checkout -b feat/your-feature-name"
fi

# 用 git config 查 upstream remote 與 merge ref（避免 @{upstream} zsh 問題）
REMOTE=$(git_cmd config "branch.${BRANCH}.remote" 2>/dev/null || echo "")
MERGE=$(git_cmd config "branch.${BRANCH}.merge" 2>/dev/null || echo "")

if [ "$REMOTE" = "origin" ] && [[ "$MERGE" =~ ^refs/heads/(main|master)$ ]]; then
    block_push "BLOCKED: branch '$BRANCH' 追蹤 origin/main！\n推送會直接到 main，繞過 PR 流程。\n\n請先修正 tracking 再 push：\n  git branch --unset-upstream && git push -u origin HEAD"
fi

exit 0
