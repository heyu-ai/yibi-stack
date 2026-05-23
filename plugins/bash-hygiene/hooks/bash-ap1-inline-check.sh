#!/bin/bash
# PreToolUse hook: detect AP1 high-frequency bash anti-patterns.
# Claude Code pipes PreToolUse data as JSON to stdin:
#   {"tool_name": "Bash", "tool_input": {"command": "..."}}
#
# Detection scope (mechanically deterministic AP1 true positives):
#   1. python -c "..." with newlines -> inline Python multi-line body
#   2. osascript <<'TAG' heredoc -> should be extracted to .applescript file
#   3. grep "...\|..." double-quoted BRE alternation -> use single quotes
#   4. $(outer "$(inner)") nested subshell -> split into two bash calls
#   5. $(jq 'filter') single-quoted jq filter in subshell -> remove quotes
#
# Exit codes: 0 = allow, 2 = block

set -euo pipefail
trap 'exit 0' ERR

# shellcheck source=_audit_log.sh
source "$(dirname "$0")/_audit_log.sh"

if ! command -v python3 >/dev/null 2>&1; then
    echo "[bash-hygiene] python3 not found, AP1 checks disabled" >&2
    exit 0
fi

# fire-and-forget event logging（3 levels up from plugins/bash-hygiene/hooks/）
_LOG_SCRIPT="${BASH_SOURCE[0]%/*}/../../../scripts/log_bash_hygiene_event.py"
_RULE_ID="13"

_log_block() {
    # $1 = pattern  $2 = cmd  $3 = rule_id (defaults to _RULE_ID)
    [ -f "$_LOG_SCRIPT" ] || return 0
    python3 "$_LOG_SCRIPT" ap1 "$1" "$2" "${3:-$_RULE_ID}" block >/dev/null 2>&1 &
    disown 2>/dev/null || true
}

STDIN_DATA=$(cat 2>/dev/null || true)

CMD=$(printf '%s' "${STDIN_DATA:-}" | python3 -c "
import sys, json
try:
    data = json.loads(sys.stdin.read())
    cmd = data.get('tool_input', {}).get('command', '')
    sys.stdout.write(cmd)
except Exception:
    pass
" 2>/dev/null || true)

[ -z "${CMD:-}" ] && { audit_allow || true; exit 0; }

# Helper: print block messages, record audit event, then exit 2.
# Usage: block "reason-slug" "line1" "line2" ...
block() {
    local reason="$1"; shift
    for msg in "$@"; do echo "$msg"; done
    audit_block "$reason" "$_RULE_ID" || true
    exit 2
}

# git commit message exemption
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
    [ "${IS_COMMIT_HEREDOC:-}" = "yes" ] && { audit_allow || true; exit 0; }
fi

# Detection 1: python -c with newlines (checks all occurrences via finditer)
PYTHON_MATCH=$(printf '%s' "$CMD" | python3 -c "
import re, sys
cmd = sys.stdin.read()
dq = chr(34)
sq = chr(39)
bs = chr(92)
dl = chr(36)
for m in re.finditer(r'python[0-9]*(?:\.[0-9]+)*(?:\s+-\w+)*\s+-c', cmd):
    after_c = cmd[m.end():]
    m2 = re.match(r'\s*' + dq + r'((?:[^' + dq + bs + bs + r']|' + bs + bs + r'.)*)'+ dq, after_c, re.DOTALL)
    if m2:
        if chr(10) in m2.group(1): print('yes'); sys.exit(0)
        continue
    m2 = re.match(r'\s*' + sq + r'([^' + sq + r']*)' + sq, after_c, re.DOTALL)
    if m2:
        if chr(10) in m2.group(1): print('yes'); sys.exit(0)
        continue
    m2 = re.match(r'\s*' + bs + dl + sq + r'((?:[^' + sq + bs + bs + r']|' + bs + bs + r'.)*)'+ sq, after_c, re.DOTALL)
    if m2:
        body = m2.group(1)
        if chr(10) in body or (bs + 'n') in body: print('yes'); sys.exit(0)
        continue
    if chr(10) in after_c: print('yes'); sys.exit(0)
" 2>/dev/null || true)

if [ "${PYTHON_MATCH:-}" = "yes" ]; then
    _log_block "python_c_multiline" "$CMD"
    block "python-c-multiline" \
        "BLOCKED: python -c multi-line body detected (AP1)" \
        "" \
        "Multi-line python -c violates Anti-Pattern 1 (score: multi-line + inline Python >= 2)" \
        "" \
        "Fix: extract Python logic into a standalone .py file"
fi

# Detection 2: osascript heredoc
OSASCRIPT_MATCH=$(printf '%s' "$CMD" | python3 -c "
import re, sys
cmd = sys.stdin.read()
if re.search(r'osascript\b[^&|;\n]*<<', cmd):
    print('yes')
" 2>/dev/null || true)

if [ "${OSASCRIPT_MATCH:-}" = "yes" ]; then
    _log_block "osascript_heredoc" "$CMD"
    block "osascript-heredoc" \
        "BLOCKED: osascript heredoc detected (AP1)" \
        "" \
        "osascript heredoc violates Anti-Pattern 1 (score: multi-line heredoc + inline AppleScript >= 2)" \
        "" \
        "Fix: extract AppleScript into a standalone .applescript file"
fi

# Detection 3: grep "...\|..." double-quoted BRE alternation
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
    block "grep-bre-doublequote" \
        "BLOCKED: grep double-quoted BRE alternation (AP1)" \
        "" \
        "Fix: use single quotes or -E flag" \
        "  A) grep -i 'pat1\|pat2'" \
        "  B) grep -Ei 'pat1|pat2'"
fi

# Detection 4: $(outer "$(inner)") nested subshell
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
    block "nested-subshell" \
        "BLOCKED: \$(outer \"\$(inner)\") nested subshell (AP1)" \
        "" \
        "Fix: split into two separate bash calls"
fi

# Detection 5: $(jq 'filter') single-quoted jq filter in subshell
# The regex below lives inside a bash double-quoted string, so bash escaping
# applies first: r'\\\$' -> bash sees \\$ -> Python receives r'\$' (literal $).
# Final Python pattern: \$\(jq\s[^)]*'[^'$]+'
JQ_FILTER_MATCH=$(printf '%s' "$CMD" | python3 -c "
import re, sys
cmd = sys.stdin.read()
sq = chr(39)
ptn = r'\\\$\(jq\s[^)]*' + sq + '[^' + sq + r'\\\$' + ']+' + sq
if re.search(ptn, cmd):
    print('yes')
" 2>/dev/null || true)

if [ "${JQ_FILTER_MATCH:-}" = "yes" ]; then
    _log_block "jq_single_quote_filter" "$CMD"
    block "jq-singlequote-filter" \
        "BLOCKED: \$(jq '...') single-quoted filter in subshell (AP1)" \
        "" \
        "Fix: remove quotes from jq filter (jq accepts unquoted simple paths)" \
        "  Bad:  RESULT=\$(jq -r '.key' file.json)" \
        "  Good: RESULT=\$(jq -r .key file.json)"
fi

# Detection 6: rg '...\|...' BRE alternation misuse in ERE tool
# rg uses Rust ERE-like regex: | is alternation, \| is literal pipe.
# BRE \| syntax returns 0 results silently when searching for literal pipe.
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
    block "rg-bre-misuse" \
        "BLOCKED: rg pattern BRE alternation misuse (Detection 6)" \
        "" \
        "rg uses Rust ERE-like regex: | is alternation, \\| is literal pipe." \
        "Pattern with \\| searches for literal pipe, not alternation. Results silently empty." \
        "" \
        "Fix (choose one):" \
        "  A) Use Claude Code built-in Grep tool (pattern uses | for alternation)" \
        "  B) rg ERE syntax: rg -rl 'pat1|pat2|pat3' /path" \
        "  C) Multiple -e flags: rg -l -e 'pat1' -e 'pat2' /path"
fi

audit_allow || true
exit 0
