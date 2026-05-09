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

# 解析 -C 路徑（支援 $VAR 和 literal path）
GIT_DIR=$(python3 -c '
import sys, re
cmd = sys.stdin.read().strip()
c_match = re.search(r"git\s+-C\s+" + chr(34) + r"?(\$\w+|[^\s" + chr(34) + r"]+)" + chr(34) + r"?", cmd)
if not c_match:
    print("")
    sys.exit(0)
raw = c_match.group(1)
if raw.startswith("$"):
    varname = raw[1:]
    var_match = re.search(r"\b" + re.escape(varname) + r"=(?:" + chr(34) + r"([^" + chr(34) + r"]*)" + chr(34) + r"|([^\s;&|]+))", cmd)
    if var_match:
        print(var_match.group(1) or var_match.group(2))
    else:
        print("")
else:
    print(raw)
' <<< "$CMD" 2>/dev/null || echo "")

# 取得目前 branch（使用 -C 路徑若有的話）
if [[ -n "$GIT_DIR" ]]; then
  BRANCH=$(git -C "$GIT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
else
  BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
fi

[ -z "$BRANCH" ] && exit 0

# main/master branch 直接 push 也應該擋住（這是 worktree 忘記切 branch 的情況）
if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
    MSG="BLOCKED: 目前在 '$BRANCH' branch！"
    MSG="$MSG\n直接 push 到 $BRANCH 會繞過 PR 流程。"
    MSG="$MSG\n\n請先建立 feature branch："
    MSG="$MSG\n  git checkout -b feat/your-feature-name"
    printf '{"decision":"block","reason":"%s"}\n' "$MSG"
    exit 0
fi

# 用 git config 查 upstream remote 與 merge ref（避免 @{upstream} zsh 問題）
if [[ -n "$GIT_DIR" ]]; then
  REMOTE=$(git -C "$GIT_DIR" config "branch.${BRANCH}.remote" 2>/dev/null || echo "")
  MERGE=$(git -C "$GIT_DIR" config "branch.${BRANCH}.merge" 2>/dev/null || echo "")
else
  REMOTE=$(git config "branch.${BRANCH}.remote" 2>/dev/null || echo "")
  MERGE=$(git config "branch.${BRANCH}.merge" 2>/dev/null || echo "")
fi

if [ "$REMOTE" = "origin" ] && [[ "$MERGE" =~ ^refs/heads/(main|master)$ ]]; then
    MSG="BLOCKED: branch '$BRANCH' 追蹤 origin/main！"
    MSG="$MSG\n推送會直接到 main，繞過 PR 流程。"
    MSG="$MSG\n\n請先修正 tracking 再 push："
    MSG="$MSG\n  git branch --unset-upstream && git push -u origin HEAD"
    printf '{"decision":"block","reason":"%s"}\n' "$MSG"
    exit 0
fi

exit 0
