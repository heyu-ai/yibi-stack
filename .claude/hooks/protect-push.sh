#!/bin/bash
# PreToolUse hook: 防止危險的 git/gh 操作直接修改 main
# Claude Code pipes PreToolUse data as JSON to stdin:
#   {"tool_name": "Bash", "tool_input": {"command": "..."}}
#
# 保護範圍：
#   1. gh pr merge → BLOCK（需使用者在 chat 中明確指示）
#   2. git push 到 main/master → BLOCK（直推保護分支）
#   3. worktree branch 追蹤 origin/main 時 git push → BLOCK
#   4. push 到「PR 已 merged/closed」的分支 → BLOCK（委派給 protect_push_pr_state.py；
#      該檔 docstring 有完整理由與逐條 fail-open 條件。逃生口：PROTECT_PUSH_SKIP_PR_STATE=1）
#
# Exit code 規範（Claude Code PreToolUse 約定）：
#   exit 0  → 放行，工具正常執行
#   exit 2  → 攔截，中止工具呼叫；訊息必須寫到 stderr（探針：stdout 的訊息不會送達 model）
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
parts = re.split(r'&&|\|\||[;|\n]', cmd)
for part in parts:
    stripped = part.strip().lstrip('(').strip()
    if re.match(r'gh\s+pr\s+merge\b', stripped):
        print('yes')
        break
" 2>/dev/null || true)

if [ "${GH_MATCH:-}" = "yes" ]; then
    echo "BLOCKED: 偵測到 gh pr merge 指令！" >&2
    echo "" >&2
    echo "合併 PR 是高風險、不可逆的操作。" >&2
    echo "請在對話中明確輸入「確認合併」或「merge the PR」後，Claude 才可執行。" >&2
    exit 2
fi

# ── 保護 2 & 3：git push 相關 ────────────────────────────────────────
# Fast-exit: skip if no "git push" or "git -C ... push" pattern.
# Must also check for "git"..."push" to catch git -C <path> push commands.
[[ "$CMD" != *"git"*"push"* ]] && exit 0

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
parts = re.split(r'&&|\|\||[;|\n]', cmd)
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
    echo "BLOCKED: 禁止直接 git push 到 main/master！" >&2
    echo "" >&2
    echo "請透過 PR 流程：建立 feature branch → push → gh pr create → 請使用者確認後合併" >&2
    exit 2
fi

# 保護 3：worktree branch 追蹤 origin/main
# main/master 本身由保護 2 處理；此處只處理其他 branch 追蹤 origin/main 的情況
#
# 凡是目的地由 tracking 決定的 push 都要查：裸 push，以及 refspec 沒有 :<dst> 的 push
# （push.default=upstream 下，git push origin <branch> 會依該 branch 的 tracking 推送）。
# 只有每個 refspec 都明確寫出 non-main 的 :<dst> 才直接放行。
# 同時過濾 CMD 中只含 git push 文字（如 commit message、echo 字串）的情況。
PUSH_MODE=$(echo "$CMD" | python3 -c "
import re, shlex, sys
cmd = sys.stdin.read()
parts = re.split(r'&&|\|\||[;|\n]', cmd)
# Strip leading VAR=value env assignments (P2: handle GIT_SSH_COMMAND='...' git push)
_env_re = re.compile(r'^(?:\w+=(?:[^\s\'\"]+|\'[^\']*\'|\"[^\"]*\")\s+)*')
push_found = False
bare_found = False
# 需要查 tracking 的 branch：HEAD 代表目前所在的 branch
track = []
for part in parts:
    stripped = _env_re.sub('', part.strip().lstrip('(').strip())
    if not re.match(r'git\s+push\b', stripped):
        continue
    push_found = True
    # 移除 flag（以 - 開頭的 token），取 positional args：[git, push, [remote], [dest]]
    # 特別處理「需要 argument 的 flag」（如 -o / --push-option）：同時跳過其 argument token
    _arg_opts = {'-o', '--push-option', '--receive-pack', '--exec', '--repo'}
    # 用 shell 規則切 token：引號、跳脫字元要先拿掉，否則 'feat' 這種寫法查不到 tracking。
    # 切不開（例如引號沒有閉合）就當成裸 push，查目前 branch 的 tracking。
    try:
        tokens = shlex.split(stripped)
    except ValueError:
        bare_found = True
        track.append('HEAD')
        continue
    positional = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.startswith('-'):
            if '=' not in t and t in _arg_opts:
                i += 2  # 跳過 flag + argument
            else:
                i += 1  # 只跳過 flag
        else:
            positional.append(t)
            i += 1
    if len(positional) >= 4:
        # Check ALL refspecs (positional[3], [4], ...) — multiple refspecs are valid.
        # Only mark explicit-other when every refspec is provably safe.
        # 不在第一個可疑 refspec 就停：後面沒有 :dst 的 branch 也要查 tracking
        for dest in positional[3:]:
            # shell expansion or backtick -> unresolvable, treat as bare
            # (backtick is \x60; no bare dollar signs in this comment)
            if re.search(r'[$\x60]', dest):
                bare_found = True
                track.append('HEAD')
                continue
            # glob pattern -> unsafe
            if '*' in dest or '?' in dest:
                bare_found = True
                track.append('HEAD')
                continue
            if ':' in dest:
                rhs = dest.rsplit(':', 1)[1]
                # empty rhs (delete refspec) or main/HEAD rhs -> bare
                if not rhs or re.match(
                    r'^(HEAD|main|master|refs/heads/(main|master))$', rhs
                ):
                    bare_found = True
                    track.append('HEAD')
                # else: explicit non-main rhs -> safe, continue checking
                continue
            # 沒有 :<dst>：push.default=upstream 下，git 依「這個 branch 的 tracking」決定
            # 目的地，追蹤 origin/main 的 branch 會直推 main（-u 也一樣）。
            # 正規化成 branch 名再查 tracking：去掉強制推的 +、refs/heads/ 或 heads/，@ 等於 HEAD。
            src = re.sub(r'^(refs/heads/|heads/)', '', dest.lstrip('+'))
            if src in ('@', ''):
                src = 'HEAD'
            bare_found = True
            track.append(src)
    else:
        # 裸 push（無明確目的地）-> 需檢查目前 branch 的 tracking
        bare_found = True
        track.append('HEAD')
# 所有 push parts 都明確指向 non-main -> 放行；否則交給 tracking 檢查
# 輸出：第一行是模式，其後每行一個要查 tracking 的 branch
if not push_found:
    print('none')
elif not bare_found:
    print('explicit-other')
else:
    print('bare')
    for b in dict.fromkeys(track):
        print(b)
" 2>/dev/null || echo "none")

TRACK_BRANCHES=$(printf '%s\n' "$PUSH_MODE" | tail -n +2)
PUSH_MODE=$(printf '%s\n' "$PUSH_MODE" | head -n 1)

# 無實際 git push 指令（僅文字）-> 放行
[ "${PUSH_MODE:-bare}" = "none" ] && exit 0

# ── 保護 4：推到 PR 已 merged/closed 的分支 ──────────────────────────
# 放在 explicit-other 早退「之前」：PR #449 的事故指令就是 explicit refspec
# （git push origin B:B），保護 3 對它直接放行，所以擺在後面等於沒掛上。
#
# 必須用 `|| RC=$?` 承接非零退出：本檔開頭的 `trap 'exit 0' ERR` 會讓任何未加保護的
# 非零指令直接以 0 結束，helper 的 exit 2 會被靜默吞掉、攔截完全失效。
# （判定細節與逐條 fail-open 條件見 protect_push_pr_state.py 的 docstring。）
# `2>&1 >/dev/null` 的順序不可對調：先把 stderr 接到擷取管線、再丟掉 stdout，只擷取 helper 的
# stderr；對調成 `>/dev/null 2>&1` 會讓 PR_STATE_OUT 恆為空，block 訊息退化成沒有 PR 號的 fallback。
PR_STATE_RC=0
PR_STATE_OUT=$(echo "$CMD" | python3 "$(dirname "$0")/protect_push_pr_state.py" 2>&1 >/dev/null) \
    || PR_STATE_RC=$?
if [ "${PR_STATE_RC:-0}" -eq 2 ]; then
    echo "${PR_STATE_OUT:-BLOCKED: 目標分支的 PR 已結束}" >&2
    exit 2
fi

# 每個 refspec 都明確寫出 non-main 的 :<dst> -> 放行；其餘交給下方逐 branch 的 tracking 檢查
[ "${PUSH_MODE:-bare}" = "explicit-other" ] && exit 0

CURRENT=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)
[ -z "${TRACK_BRANCHES:-}" ] && TRACK_BRANCHES="HEAD"

# 逐一檢查要推的 branch 是否追蹤 origin/main
while IFS= read -r TOKEN; do
    [ -z "${TOKEN:-}" ] && continue
    BRANCH="$TOKEN"
    [ "$BRANCH" = "HEAD" ] && BRANCH="${CURRENT:-}"
    [ -z "${BRANCH:-}" ] && continue
    [ "$BRANCH" = "HEAD" ] && continue  # detached HEAD 狀態，無 upstream 可查
    [ "$BRANCH" = "main" ] && continue
    [ "$BRANCH" = "master" ] && continue

    # 用 git config 查 upstream（不用 @{upstream}，避免 zsh brace expansion 靜默失效）
    REMOTE=$(git config "branch.${BRANCH}.remote" 2>/dev/null || true)
    MERGE=$(git config "branch.${BRANCH}.merge" 2>/dev/null || true)

    if [ "${REMOTE:-}" = "origin" ] && [[ "${MERGE:-}" =~ ^refs/heads/(main|master)$ ]]; then
        echo "BLOCKED: branch '${BRANCH}' 追蹤 origin/main！" >&2
        echo "沒有指定 :<dst> 的 push 會依 tracking 直接推到 main（-u 也一樣），繞過 PR 流程。" >&2
        echo "" >&2
        echo "請明確指定目的地：" >&2
        echo "  git push -u origin ${BRANCH}:${BRANCH}" >&2
        exit 2
    fi
done <<< "$TRACK_BRANCHES"

exit 0
