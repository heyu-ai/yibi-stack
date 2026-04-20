#!/bin/bash
# PreToolUse hook: 防止危險的 git/gh 操作直接修改 main
# Claude Code pipes PreToolUse data as JSON to stdin:
#   {"tool_name": "Bash", "tool_input": {"command": "..."}}
#
# 保護範圍：
#   1. gh pr merge → BLOCK（需使用者在 chat 中明確指示）
#   2. git push 到 main/master → BLOCK（直推保護分支）
#   3. worktree branch 追蹤 origin/main 時 git push → BLOCK
#
# Exit code 規範（Claude Code PreToolUse 約定）：
#   exit 0  → 放行，工具正常執行
#   exit 2  → 攔截，中止工具呼叫並顯示 stdout 訊息
#   （exit 1 不攔截，僅表示 hook 本身出錯）
#
# 安裝方式：參考 skills/protect-push/SKILL.md

# 不用 set -e：避免任何意外子指令失敗導致 hook 誤攔截
# 有 set -u：所有變數存取需加 ${VAR:-} 預設值，否則未設定時立即 exit（非零）
# trap ERR：任何未預期的 set -u 或 pipefail 錯誤都強制 exit 0（fail-open）
set -uo pipefail
trap 'exit 0' ERR

# ── 解析指令 ─────────────────────────────────────────────────────────
STDIN_DATA=$(cat 2>/dev/null || true)

# python3 不存在或 JSON 解析失敗時，CMD 為空字串 → 放行
CMD=$(echo "${STDIN_DATA:-}" | python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    print(data.get('tool_input', {}).get('command', ''))
except Exception:
    pass
" 2>/dev/null || true)

# 解析失敗或空指令 → 放行
[ -z "${CMD:-}" ] && exit 0

# ── 保護 1：gh pr merge ──────────────────────────────────────────────
# 用 re.split 切出獨立指令單元，再用 re.match（開頭錨定）檢查。
# 只有真正以 gh pr merge 開頭的指令單元才會觸發——
# commit message 或 echo 字串中含有此字串時，其單元以 git / echo 開頭，不匹配。
GH_MATCH=$(echo "$CMD" | python3 -c "
import re, sys
cmd = sys.stdin.read()
parts = re.split(r'[;|\n]|&&|\|\|', cmd)
for part in parts:
    stripped = part.strip().lstrip('(').strip()
    if re.match(r'gh\s+pr\s+merge\b', stripped):
        print('yes')
        break
" 2>/dev/null || true)

if [ "${GH_MATCH:-}" = "yes" ]; then
    echo "BLOCKED: 偵測到 gh pr merge 指令！"
    echo ""
    echo "合併 PR 是高風險、不可逆的操作。"
    echo "請在對話中明確輸入「確認合併」或「merge the PR」後，Claude 才可執行。"
    exit 2
fi

# ── 保護 2 & 3：git push 相關 ────────────────────────────────────────
# [[ ]] 的 * 在 pattern 模式下可跨換行比對（與 filename glob 不同）
[[ "$CMD" != *"git push"* ]] && exit 0

# 保護 2：直接推 main/master（同樣採用 command-boundary detection，避免 false positive）
# 涵蓋語法（均有測試覆蓋）：
#   git push origin main              （基本形式）
#   git push -f origin main           （短旗標 -f）
#   git push --force origin main      （長旗標）
#   git push --force-with-lease origin main
#   git push origin HEAD:main         （refspec 語法，推當前 HEAD 到 main）
#   git push origin refs/heads/main   （完整 ref 語法）
PUSH_MAIN_MATCH=$(echo "$CMD" | python3 -c "
import re, sys
cmd = sys.stdin.read()
parts = re.split(r'[;|\n]|&&|\|\|', cmd)
for part in parts:
    stripped = part.strip().lstrip('(').strip()
    # 必須是 git push 指令（以 git push 開頭，非 git commit、git pull 等）
    if not re.match(r'git\s+push\b', stripped):
        continue
    # 必須指向 origin，且目的地為 main/master（含 refspec 及完整 ref 形式）
    if (re.search(r'\borigin\b', stripped) and
            re.search(
                r'\b(main|master|refs/heads/(?:main|master)|HEAD:(?:main|master))\b',
                stripped,
            )):
        print('yes')
        break
" 2>/dev/null || true)

if [ "${PUSH_MAIN_MATCH:-}" = "yes" ]; then
    echo "BLOCKED: 禁止直接 git push 到 main/master！"
    echo ""
    echo "請透過 PR 流程：建立 feature branch → push → gh pr create → 請使用者確認後合併"
    exit 2
fi

# 保護 3：worktree branch 追蹤 origin/main
# main/master 本身由保護 2 處理；此處只處理其他 branch 追蹤 origin/main 的情況
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)
[ -z "${BRANCH:-}" ] && exit 0
[ "$BRANCH" = "HEAD" ] && exit 0  # detached HEAD 狀態，無 upstream 可查
[ "$BRANCH" = "main" ] && exit 0
[ "$BRANCH" = "master" ] && exit 0

# 用 git config 查 upstream（不用 @{upstream}，避免 zsh brace expansion 靜默失效）
REMOTE=$(git config "branch.${BRANCH}.remote" 2>/dev/null || true)
MERGE=$(git config "branch.${BRANCH}.merge" 2>/dev/null || true)

if [ "${REMOTE:-}" = "origin" ] && [[ "${MERGE:-}" =~ ^refs/heads/(main|master)$ ]]; then
    echo "BLOCKED: branch '${BRANCH}' 追蹤 origin/main！"
    echo "推送會直接到 main，繞過 PR 流程。"
    echo ""
    echo "請先修正 tracking 再 push："
    echo "  git branch --unset-upstream && git push -u origin HEAD"
    exit 2
fi

exit 0
