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

exit 0
