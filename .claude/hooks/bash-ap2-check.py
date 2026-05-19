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

規則來源：.claude/rules/13-bash-anti-patterns.md（Anti-Pattern 2）
"""

import json
import re
import sys

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

_VIOLATION_MESSAGE = """\
[AP2 VIOLATION] bash 指令含禁用 Unicode 字元（em dash / en dash / emoji / 零寬空白）。

依 .claude/rules/13-bash-anti-patterns.md（Anti-Pattern 2）修正後重新執行：

  em dash (—)  ->  --
  en dash (–)  ->  -
  emoji (⚠ ✅ ⏭ ...)  ->  [WARN] / [OK] / [SKIP] / [FAIL]
  零寬空白  ->  刪除

注意：hook 掃描 raw 指令字串，echo 內的 emoji 也會觸發。"""


def _scannable(command: str) -> str:
    """Strip git commit message payloads — commit messages are AP2-exempt per rule 13."""
    # [^;|\n&]* allows flags between git and commit, e.g. git -C /path commit
    if re.search(r"(?:^|[;|\n]|&&|\|\|)\s*(?:\(\s*)?git\b[^;|\n&]*\bcommit\b", command):
        return _COMMIT_MSG_RE.sub("", command)
    return command


def main() -> None:
    try:
        data = json.load(sys.stdin)
        if data.get("tool_name") != "Bash":
            sys.exit(0)
        command = data.get("tool_input", {}).get("command", "")
    except Exception:
        sys.exit(0)

    if not _AP2.search(_scannable(command)):
        sys.exit(0)

    print(_VIOLATION_MESSAGE)
    sys.exit(2)


if __name__ == "__main__":
    main()
