#!/bin/bash
# PreToolUse hook: 偵測 AP1 高頻違規模式
# Claude Code pipes PreToolUse data as JSON to stdin:
#   {"tool_name": "Bash", "tool_input": {"command": "..."}}
#
# 偵測範圍（機械性可判定的 AP1 真陽性）：
#   1. python -c "..." 含換行 → inline Python multi-line body
#      含 ANSI-C quoting ($'...\n...')、點版本號 (python3.11 -c)、常用 flag (-I/-B)
#   2. osascript <<'TAG' heredoc → 應提取為 .applescript 檔案
#      含帶 -l 語言 flag 的形式（如 osascript -l JavaScript <<'TAG'）
#
# 範圍外（語意複雜，不在本 hook 偵測）：
#   - cd /abs/path && cmd（CWD 污染）→ 靠 prompt rule 指引
#   - cmd | grep -v "..."（output filter）→ 靠 prompt rule 指引
#
# Exit code 規範：
#   exit 0  → 放行
#   exit 2  → 攔截，中止工具呼叫並顯示 stdout 訊息
#   （exit 1 不攔截，僅表示 hook 本身出錯）

# fail-open 設計：hook 自身任何錯誤都放行，不誤擋正常操作
set -uo pipefail
trap 'exit 0' ERR

# ── 解析指令 ─────────────────────────────────────────────────────────
STDIN_DATA=$(cat 2>/dev/null || true)

# 使用 printf '%s' 傳遞，避免 echo 加 trailing newline 干擾後續偵測
CMD=$(printf '%s' "${STDIN_DATA:-}" | python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    cmd = data.get('tool_input', {}).get('command', '')
    sys.stdout.write(cmd)
except Exception:
    pass
" 2>/dev/null || true)

[ -z "${CMD:-}" ] && exit 0

# ── git commit message 豁免 ──────────────────────────────────────────
# git commit -m "$(cat <<'EOF'...)" 格式的 commit message 內含範例程式碼時，
# 會對 Case 25/26 偵測器產生 false positive（與 AP2 hook 的豁免邏輯對應）。
# bash 字串匹配作為廉價前置過濾，只在確實是 git commit 時才啟動 python3。
if [[ "${CMD:-}" == *"git commit"* ]]; then
    IS_COMMIT_HEREDOC=$(printf '%s' "${CMD:-}" | python3 -c "
import re, sys
cmd = sys.stdin.read()
bs = chr(92)
dl = chr(36)
dq = chr(34)
ptn = r'\bgit\s+commit\b[^;|&\n]*-[a-zA-Z]*m\s+' + dq + bs + dl + r'\(cat\s+<<'
if re.search(ptn, cmd):
    print('yes')
" 2>/dev/null || true)
    [ "${IS_COMMIT_HEREDOC:-}" = "yes" ] && exit 0
fi

# ── 偵測 1：python -c 含換行 ──────────────────────────────────────────
# 判斷：指令包含 python -c（含版本號、點版本號、常用 flag 如 -I/-B）且 -c 引數體為多行
#   - 支援：python3 -c / python3  -c（多空格）/ python3 -I -c（帶 flag）
#   - 多行判斷只掃 -c 引數體本身，避免誤攔後接的 heredoc / 指令鏈
#   - 引號形式：雙引號、單引號、ANSI-C quoting（$'...\n...'）
PYTHON_MATCH=$(printf '%s' "$CMD" | python3 -c "
import re, sys
cmd = sys.stdin.read()
m = re.search(r'python[0-9]*(?:\.[0-9]+)*(?:\s+-\w+)*\s+-c', cmd)
if not m:
    sys.exit(0)
after_c = cmd[m.end():]
dq = chr(34)
sq = chr(39)
bs = chr(92)
dl = chr(36)
m2 = re.match(r'\s*' + dq + r'((?:[^' + dq + bs + bs + r']|' + bs + bs + r'.)*)'+ dq, after_c, re.DOTALL)
if m2:
    if '\n' in m2.group(1): print('yes')
    sys.exit(0)
m2 = re.match(r'\s*' + sq + r'([^' + sq + r']*)' + sq, after_c, re.DOTALL)
if m2:
    if '\n' in m2.group(1): print('yes')
    sys.exit(0)
m2 = re.match(r'\s*' + bs + dl + sq + r'((?:[^' + sq + bs + bs + r']|' + bs + bs + r'.)*)'+ sq, after_c, re.DOTALL)
if m2:
    body = m2.group(1)
    if '\n' in body or (bs + 'n') in body: print('yes')
    sys.exit(0)
if '\n' in after_c: print('yes')
" 2>/dev/null || true)

if [ "${PYTHON_MATCH:-}" = "yes" ]; then
    echo "BLOCKED: python -c multi-line body detected (AP1)"
    echo ""
    echo "多行 python -c 違反 Anti-Pattern 1（score: 多行 + 內嵌 Python >= 2）"
    echo ""
    echo "修法："
    echo "  1. 將 Python 邏輯提取成獨立 .py 檔案"
    echo "  2. 用 uv run --directory /path python3 scripts/xxx.py 取代 cd + inline"
    exit 2
fi

# ── 偵測 2：osascript heredoc ─────────────────────────────────────────
# 判斷：指令包含 osascript + heredoc（含帶 flag 的形式如 osascript -l JavaScript <<）
#   - 使用 [^&|;\n]* 確保 << 與 osascript 在同一指令段，不跨越 && / || / ;
OSASCRIPT_MATCH=$(printf '%s' "$CMD" | python3 -c "
import re, sys
cmd = sys.stdin.read()
if re.search(r'osascript\b[^&|;\n]*<<', cmd):
    print('yes')
" 2>/dev/null || true)

if [ "${OSASCRIPT_MATCH:-}" = "yes" ]; then
    echo "BLOCKED: osascript heredoc detected (AP1)"
    echo ""
    echo "osascript heredoc 違反 Anti-Pattern 1（score: 多行 heredoc + 內嵌 AppleScript >= 2）"
    echo "heredoc 豁免僅適用 commit message 純文字，不適用 DSL/腳本 heredoc。"
    echo ""
    echo "修法：將 AppleScript 提取成獨立 .applescript 檔案"
    echo "  osascript scripts/xxx.applescript"
    exit 2
fi

# ── 偵測 3：grep "...\|..." 雙引號 BRE alternation ─────────────────────
# 判斷：grep（含 flag，排除 -E/--extended-regexp ERE 模式）後接雙引號字串內含 \|
#   - \| 在雙引號 grep pattern 內讓 bash 靜態分析器回報 Unhandled node type: string
#   - 即使 AP1 score 僅 1/5 也觸發（Case 25）
GREP_BRE_MATCH=$(printf '%s' "$CMD" | python3 -c "
import re, sys
cmd = sys.stdin.read()
bs = chr(92)
dq = chr(34)
if not re.search(r'\bgrep\b', cmd):
    sys.exit(0)
found = False
for m in re.finditer(dq + r'([^' + dq + r']*)' + dq, cmd):
    if bs + '|' not in m.group(1):
        continue
    before = cmd[:m.start()]
    greps = list(re.finditer(r'\bgrep\b', before))
    if not greps:
        continue
    between = cmd[greps[-1].end():m.start()]
    if re.search(r'-[a-zA-Z]*E[a-zA-Z]*\b|--extended-regexp', between):
        continue
    found = True
    break
if found:
    print('yes')
" 2>/dev/null || true)

if [ "${GREP_BRE_MATCH:-}" = "yes" ]; then
    echo "BLOCKED: grep double-quoted BRE alternation (AP1 D 類)"
    echo ""
    echo "grep 雙引號 pattern 內含 \| 觸發 Unhandled node type: string。"
    echo "即使 AP1 score 1/5，hook 仍觸發（Case 25）。"
    echo ""
    echo "修法（擇一）："
    echo "  A) 單引號 BRE：grep -i 'pat1\|pat2'"
    echo "  B) ERE flag：  grep -Ei 'pat1|pat2'"
    echo "  C) 拆成多個 grep call"
    exit 2
fi

# ── 偵測 4：$(outer "$(inner)") 反向巢狀 subshell ─────────────────────
# 判斷：外層 $() 內含雙引號包裹的內層 $()，回報 Unhandled node type: string
#   - 是 Case 20 echo "$(cmd "$VAR")" 的反向變體（Case 26）
# 使用 stack-based state machine：正確跳過 "..." / '...' 內的 ) 字元，
# 避免 echo ") (" && cmd "$(inner)" 這類 literal ) 造成計數錯誤。
NESTED_SUBSHELL_MATCH=$(printf '%s' "$CMD" | python3 -c "
import sys
cmd = sys.stdin.read()
dl = chr(36)
dq = chr(34)
sq = chr(39)
if dl + '(' not in cmd:
    sys.exit(0)
def subshell_depth(s):
    stack = []
    i = 0
    while i < len(s):
        c = s[i]
        top = stack[-1] if stack else None
        if top == sq:
            if c == sq:
                stack.pop()
        elif top == dq:
            if c == dq:
                stack.pop()
            elif c == dl and i + 1 < len(s) and s[i + 1] == '(':
                stack.append(dl)
                i += 1
        else:
            if c == sq:
                stack.append(sq)
            elif c == dq:
                stack.append(dq)
            elif c == dl and i + 1 < len(s) and s[i + 1] == '(':
                stack.append(dl)
                i += 1
            elif c == ')' and top == dl:
                stack.pop()
        i += 1
    return sum(1 for x in stack if x == dl)
found = False
for i in range(len(cmd) - 2):
    if cmd[i] == dq and cmd[i + 1] == dl and cmd[i + 2] == '(':
        if subshell_depth(cmd[:i]) > 0:
            found = True
            break
if found:
    print('yes')
" 2>/dev/null || true)

if [ "${NESTED_SUBSHELL_MATCH:-}" = "yes" ]; then
    echo "BLOCKED: \$(outer \"\$(inner)\") nested subshell (AP1 D 類)"
    echo ""
    echo "外層 \$() 包雙引號包內層 \$() 觸發 Unhandled node type: string（Case 26）。"
    echo ""
    echo "修法：拆成兩個獨立 bash call"
    echo "  bash call 1：取得內層輸出"
    echo "    GIT_COMMON=\$(git rev-parse --git-common-dir)"
    echo "  bash call 2：用結果"
    echo "    dirname \"\$GIT_COMMON\""
    exit 2
fi

exit 0
