#!/usr/bin/env python3
"""PreToolUse hook: AP2 bash 指令 Unicode 反模式檢查。

Exit code:
  0 -> 放行
  2 -> 攔截（block）並顯示 stdout 訊息

禁用字元範圍（bash 指令字串內）：
  - em dash (U+2014)、en dash (U+2013)、零寬字元 U+200B/U+200C/U+200D
  - 雜項技術符號 U+2300-U+23FF（warning sign、next-track button 等）
  - 雜項符號 + Dingbats U+2600-U+27BF（check mark、warning 等）
    ※ U+2400-U+25FF（Box Drawing、Geometric Shapes 等）刻意排除，避免 tree 輸出誤攔
  - 常用 emoji U+1F000-U+1FAFF（含 Symbols and Pictographs Extended-A）

豁免範圍（不掃描）：
  - git commit -m / --message 的訊息內容（rule 13 明定 commit message 不限制）
  - python -m tasks.session_memory 之後的 --flag "value" 引數值
    （handover topic/summary 等為使用者資料，不是 bash 控制結構）

規則來源：.claude/rules/13-bash-anti-patterns.md（Anti-Pattern 2）
"""

import json
import pathlib
import re
import subprocess  # nosec B404
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from _audit_log import log_event as _log_event
except Exception:  # pragma: no cover

    def _log_event(*_a: object, **_kw: object) -> None:  # type: ignore[misc]
        pass


_LOG_SCRIPT = pathlib.Path(__file__).parent.parent.parent / "scripts" / "log_bash_hygiene_event.py"


def _log_block(pattern: str, cmd: str) -> None:
    if not _LOG_SCRIPT.exists():
        return
    subprocess.Popen(  # nosec B603
        [sys.executable, str(_LOG_SCRIPT), "ap2", pattern, cmd, "13", "block"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


_AP2 = re.compile(
    r"["
    r"\u2013\u2014"  # en/em dash
    r"\u200b-\u200d"  # zero-width chars (ZWSP/ZWNJ/ZWJ)
    r"\u2300-\u23ff"  # Misc Technical (warning sign 等)
    r"\u2600-\u27bf"  # Misc Symbols + Dingbats (check mark 等)
    r"\U0001F000-\U0001FAFF"  # Emoji (含 Extended-A)
    r"]"
)

# 匹配 git commit -m "..." 或 --message "..." 的訊息 payload
_COMMIT_MSG_RE = re.compile(
    r"""\s+(?:-[a-zA-Z]*m|--message)\s+(?:\"[^\"]*\"|'[^']*'|\S+)"""
    r"""|\s+--message=(?:\"[^\"]*\"|'[^']*'|\S+)"""
)

# 允許出現在 git 與 commit 子命令之間的全域 flag（來源：man git OPTIONS）。
# 精確枚舉可防止 git notes add / git log --grep commit 等非 commit 指令觸發豁免。
# Known Limitation: -c user.name="foo | bar" commit -- \S+ 無引號感知，quoted | 中斷匹配，豁免失敗。
_GIT_GLOBAL_FLAG = (
    r"(?:\s+"
    r"(?:-C\s+\S+"  # -C <path>: run as if started in <path>
    r"|-c\s+\S+"  # -c <name>=<value>: override config entry
    r"|--git-dir=\S+"
    r"|--work-tree=\S+"
    r"|--namespace=\S+"
    r"|--exec-path=\S+"
    r"|--super-prefix=\S+"
    r"|--config-env=\S+"
    r"|--attr-source=\S+"
    r"|--list-cmds=\S+"
    r"|--no-pager|--no-replace-objects|--no-optional-locks"
    r"|--paginate|--bare|-p|-P"
    r"))"
)
_GIT_COMMIT_RE = re.compile(
    r"(?:^|[;|\n]|&&|\|\|)\s*(?:\(\s*)?git\b" + _GIT_GLOBAL_FLAG + r"*\s+commit\b"
)

# 豁免：python -m tasks.session_memory 呼叫後的引數值（使用者資料，不是 bash 控制結構）
_TASKS_SM_RE = re.compile(r"-m\s+tasks\.session_memory\b")
# 匹配 --flag "value" 或 --flag 'value'（單行值，不跨 newline）
_ARG_QUOTED_VAL_RE = re.compile(r"""(--[\w-]+)(\s+)(?:"[^"\n]*"|'[^'\n]*')""")

_VIOLATION_MESSAGE = """\
[AP2 VIOLATION] bash 指令含禁用 Unicode 字元（em dash / en dash / emoji / 零寬空白）。

依 .claude/rules/13-bash-anti-patterns.md（Anti-Pattern 2）修正後重新執行：

  em dash (—)  ->  --
  en dash (–)  ->  -
  emoji (⚠ ✅ ⏭ ...)  ->  [WARN] / [OK] / [SKIP] / [FAIL]
  零寬空白  ->  刪除

注意：hook 掃描 raw 指令字串，echo 內的 emoji 也會觸發。"""


def _scannable(command: str) -> str:
    """Strip data payloads that are AP2-exempt:
    1. git commit message (rule 13)
    2. python -m tasks.session_memory --flag "value" args (user data, not bash code)
    """
    if _GIT_COMMIT_RE.search(command):
        command = _COMMIT_MSG_RE.sub("", command)
    m = _TASKS_SM_RE.search(command)
    if m:
        prefix = command[: m.end()]
        suffix = command[m.end() :]
        command = prefix + _ARG_QUOTED_VAL_RE.sub(r'\1\2""', suffix)
    return command


def main() -> None:
    start = time.monotonic()
    try:
        data = json.load(sys.stdin)
        if data.get("tool_name") != "Bash":
            sys.exit(0)
        command = data.get("tool_input", {}).get("command", "")
    except Exception:
        sys.exit(0)

    m = _AP2.search(_scannable(command))
    elapsed = int((time.monotonic() - start) * 1000)
    if not m:
        _log_event("ap2", command, exit_code=0, duration_ms=elapsed, rule_id="13")
        sys.exit(0)

    char_code = f"unicode_U+{ord(m.group(0)):05X}"
    _log_block(char_code, command)
    _log_event(
        "ap2", command, exit_code=2, block_reason="ap2-unicode", duration_ms=elapsed, rule_id="13"
    )
    print(_VIOLATION_MESSAGE)
    sys.exit(2)


if __name__ == "__main__":
    main()
