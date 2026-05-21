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

# ── 事件記錄（fire-and-forget）────────────────────────────────────────────
# Hook 永遠住在 <repo>/.claude/hooks/，用相對路徑算出 log script，
# 避免每次 PreToolUse 都 fork git（hot-path）且不依賴 git 可用。
_LOG_SCRIPT="${BASH_SOURCE[0]%/*}/../../scripts/log_bash_hygiene_event.py"

_log_block() {
    [ -f "$_LOG_SCRIPT" ] || return 0
    command -v python3 >/dev/null 2>&1 || return 0
    python3 "$_LOG_SCRIPT" ap1 "$1" "$2" >/dev/null 2>&1 &
    disown 2>/dev/null || true
}

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
# 也涵蓋 git -C /path commit 形式（flags between git and commit）。
# bash 字串匹配作為廉價前置過濾（over-broad 無妨，python3 regex 才是實際 gate）。
if [[ "${CMD:-}" == *git* && "${CMD:-}" == *commit* ]]; then
    IS_COMMIT_HEREDOC=$(printf '%s' "${CMD:-}" | python3 -c "
import re, sys
cmd = sys.stdin.read()
bs = chr(92)
dl = chr(36)
dq = chr(34)
# git 全域 flag 枚舉（來源：man git OPTIONS），允許出現在 git 與 commit 之間
# Known Limitation: -c user.name=foo|bar commit -- \S+ 無引號感知，quoted pipe 仍中斷匹配
GFLAG = (
    r'(?:\s+(?:-C\s+\S+|-c\s+\S+|--git-dir=\S+|--work-tree=\S+'
    r'|--namespace=\S+|--exec-path=\S+|--super-prefix=\S+|--config-env=\S+'
    r'|--attr-source=\S+|--list-cmds=\S+'
    r'|--no-pager|--no-replace-objects|--no-optional-locks|--paginate|--bare|-p|-P))'
)
ptn = r'\bgit\b' + GFLAG + r'*\s+commit\b[^;|&\n]*-[a-zA-Z]*m\s+' + dq + bs + dl + r'\(cat\s+<<'
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
    _log_block "python_c_multiline" "$CMD"
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
    _log_block "osascript_heredoc" "$CMD"
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
    _log_block "grep_bre_double_quote" "$CMD"
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
    _log_block "nested_subshell" "$CMD"
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

# TODO v3：偵測 5b — $(cmd "$VAR") 頂層 $() 內含 double-quoted 變數引數
# 觸發 CC 內建 "Unhandled node type: string" 但範圍比偵測 4 更廣。
# 目前暫不加入：$(dirname "$VAR") 是 Rule 4 的文件化修法，貿然攔截需先更新
# handover skill 的修法模式（test_handover_allow_001-003/005）。
# 評估後在獨立 PR 實作並同步更新 skills/session-memory/SKILL.md。

# ── 偵測 5：$(jq [flags] 'filter') 單引號 jq filter 在 subshell ─────────
# 判斷：jq 命令在 $() 內且 filter 為單引號字串（'...' 不含 $）
#   - Claude Code 內建靜態分析器對此回報 "Unhandled node type: string"
#   - 是 "string literal node in subshell" 的具體化：jq filter 幾乎不含 $，
#     因此可安全以 unquoted path 取代（jq -r .field 接受不帶引號的簡單路徑）
#   - 範圍刻意限縮到 jq，避免誤攔 awk '{print $1}'（$1 在單引號內但語意不同）
JQ_FILTER_MATCH=$(printf '%s' "$CMD" | python3 -c "
import re, sys
cmd = sys.stdin.read()
sq = chr(39)
# Pattern: \$(jq<whitespace><optional-flags>'filter-without-dollar')
# 此程式碼位於 bash double-quoted string 內，bash escape 處理會先發生：
#   r'\\\$'  ->  bash: \\ -> \ 且 \$ -> $  ->  Python 實際收到 r'\$'
#   r'\$' 在 Python regex = 匹配 literal $ (不是 end-of-string anchor chr(36))
# 最終 pattern 等同 r'\$\(jq\s[^)]*' + sq + '[^' + sq + r'\$' + ']+' + sq
ptn = r'\\\$\(jq\s[^)]*' + sq + '[^' + sq + r'\\\$' + ']+' + sq
if re.search(ptn, cmd):
    print('yes')
" 2>/dev/null || true)

if [ "${JQ_FILTER_MATCH:-}" = "yes" ]; then
    _log_block "jq_single_quote_filter" "$CMD"
    echo "BLOCKED: \$(jq '...') single-quoted filter in subshell (AP1 D 類)"
    echo ""
    echo "\$() 內的 jq 單引號 filter 觸發 Claude Code 內建 Unhandled node type: string。"
    echo ""
    echo "修法：移除 filter 的單引號（jq 接受不含特殊字元的 path 不需要引號）："
    echo "  違規：SKILL_REPO=\$(jq -r '.skill_repo' ~/.agents/config.json)"
    echo "  修法：SKILL_REPO=\$(jq -r .skill_repo ~/.agents/config.json)"
    exit 2
fi

# ── 偵測 6：rg '...\|...' BRE alternation 語法（ERE 工具誤用）─────────────
# 判斷：rg 指令中的 quoted pattern 含 \|（BRE alternation 語法）
#   - rg 使用 Rust ERE-like regex：| 是 alternation，\| 是 literal pipe 字元
#   - 典型錯誤：從 grep BRE 遷移到 rg 時沿用 \| 語法
#   - 後果：靜默搜尋含 literal pipe 字串，回傳 0 筆，無報錯
#   - 偵測範圍：單引號 pattern（最常見）與雙引號 pattern
RG_BRE_MATCH=$(printf '%s' "$CMD" | python3 -c "
import re, sys
cmd = sys.stdin.read()
bs = chr(92)
sq = chr(39)
dq = chr(34)
if not re.search(r'\brg\b', cmd):
    sys.exit(0)
found = False
for qt in (sq, dq):
    for m in re.finditer(qt + r'([^' + qt + r']*)' + qt, cmd):
        if bs + '|' not in m.group(1):
            continue
        rg_hits = list(re.finditer(r'\brg\b', cmd[:m.start()]))
        if not rg_hits:
            continue
        between = cmd[rg_hits[-1].end():m.start()]
        if re.search(r'[|&;()\n]', between):
            continue
        if re.search(r'-[a-zA-Z]*F[a-zA-Z]*\b|--fixed-strings', between):
            continue
        found = True
        break
    if found:
        break
if found:
    print('yes')
" 2>/dev/null || true)

if [ "${RG_BRE_MATCH:-}" = "yes" ]; then
    _log_block "rg_bre_alternation" "$CMD"
    echo "BLOCKED: rg pattern BRE alternation 誤用（Detection 6）"
    echo ""
    echo "rg 使用 Rust ERE-like regex：| 是 alternation，\\| 是 literal pipe 字元。"
    echo "含 \\| 的 pattern 搜尋 literal pipe，不是多選一，結果靜默為空，無報錯。"
    echo ""
    echo "修法（擇一）："
    echo "  A) 優先改用 Claude Code 內建 Grep tool（pattern 用 | 做 alternation）"
    echo "  B) rg ERE 語法：rg -rl 'pat1|pat2|pat3' /path"
    echo "  C) 多個 -e flag：rg -l -e 'pat1' -e 'pat2' /path"
    exit 2
fi

exit 0
