#!/usr/bin/env python3
"""PreToolUse hook: AP2 bash Unicode anti-pattern detection.

Exit code:
  0 -> allow
  2 -> block and display stdout message

Prohibited characters in bash command strings:
  - em dash (U+2014), en dash (U+2013), zero-width chars U+200B/U+200C/U+200D
  - Misc Technical U+2300-U+23FF, Misc Symbols + Dingbats U+2600-U+27BF
    (U+2400-U+25FF Box Drawing excluded to avoid tree output false positives)
  - Common emoji U+1F000-U+1FAFF

Exemptions:
  - git commit -m / --message / heredoc commit message content
"""

import json
import pathlib
import re
import subprocess  # nosec B404
import sys

# plugins/bash-hygiene/hooks/ は 4 層深いため parent x4 で repo root に到達
_LOG_SCRIPT = (
    pathlib.Path(__file__).parent.parent.parent.parent / "scripts" / "log_bash_hygiene_event.py"
)


def _log_block(pattern: str, cmd: str) -> None:
    if not _LOG_SCRIPT.exists():
        return
    subprocess.Popen(  # nosec B603
        [sys.executable, str(_LOG_SCRIPT), "ap2", pattern, cmd],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


_AP2 = re.compile(
    r"["
    r"–—"  # en/em dash
    r"​-‍"  # zero-width chars (ZWSP/ZWNJ/ZWJ)
    r"⌀-⏿"  # Misc Technical (warning sign etc.)
    r"☀-➿"  # Misc Symbols + Dingbats (check mark etc.)
    r"\U0001F000-\U0001FAFF"  # Emoji (incl. Extended-A)
    r"]"
)

_COMMIT_MSG_RE = re.compile(
    r"""\s+(?:-[a-zA-Z]*m|--message)\s+(?:\"[^\"]*\"|'[^']*'|\S+)"""
    r"""|\s+--message=(?:\"[^\"]*\"|'[^']*'|\S+)"""
)

_COMMIT_HEREDOC_RE = re.compile(
    r"""\bgit\s+commit\b[^;|&\n]*-[a-zA-Z]*m\s+"\$\(cat\s+<<""",
)

_VIOLATION_MESSAGE = """\
[AP2 VIOLATION] Bash command contains prohibited Unicode characters
(em dash / en dash / emoji / zero-width).

Replace per Anti-Pattern 2 rules:

  em dash  ->  --
  en dash  ->  -
  emoji    ->  [WARN] / [OK] / [SKIP] / [FAIL]
  zero-width chars  ->  remove

Note: hook scans raw command strings; emoji inside echo strings also triggers."""


def _scannable(command: str) -> str:
    """Strip git commit message payloads -- commit messages are AP2-exempt."""
    if _COMMIT_HEREDOC_RE.search(command):
        return ""
    if re.search(r"(?:^|[;\n]|&&|\|\|)\s*(?:\(\s*)?git\s+commit\b", command):
        return _COMMIT_MSG_RE.sub("", command)
    return command


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    if data.get("tool_name") != "Bash":
        sys.exit(0)

    command = data.get("tool_input", {}).get("command", "")
    if not isinstance(command, str) or not command:
        sys.exit(0)

    m = _AP2.search(_scannable(command))
    if not m:
        sys.exit(0)

    char_code = f"unicode_U+{ord(m.group(0)):05X}"
    _log_block(char_code, command)
    print(_VIOLATION_MESSAGE)
    sys.exit(2)


if __name__ == "__main__":
    main()
