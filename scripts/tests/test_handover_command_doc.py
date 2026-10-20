"""plugins/dev-cycle/commands/handover.md 的指令區塊守護測試（AC-5）。

/handover 把交班內容寫進 JSON 檔，Bash 指令列只剩檔案路徑：內容放在指令列時，會被其他 repo 的
permission deny 規則（例如 `Bash(uv run --directory * alembic upgrade*)`）當成指令比對；
`$(...)` 則會被部分 repo 的 PreToolUse hook 擋下。這裡鎖住文件的 bash 區塊不得退回舊寫法。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HANDOVER_DOC = REPO_ROOT / "plugins" / "dev-cycle" / "commands" / "handover.md"

_BASH_FENCE = re.compile(r"^```bash\n(.*?)^```", re.M | re.S)
_CONTENT_FLAGS = (
    "--topic",
    "--summary",
    "--completed",
    "--decisions",
    "--blocked",
    "--next",
    "--lessons",
    "--approaches",
    "--tags",
)
_WRITE_LINE = '~/.agents/bin/handover write --from-file "<FILE>"'


def _bash_fences() -> list[str]:
    fences = _BASH_FENCE.findall(HANDOVER_DOC.read_text(encoding="utf-8"))
    assert fences, f"{HANDOVER_DOC} 找不到任何 ```bash 區塊，解析前提不成立"
    return fences


def test_hcd_vl_001_no_command_substitution_in_bash_fences() -> None:
    """HCD-VL-001：bash 區塊不得出現 $(...)，避免撞上擋 command substitution 的 hook。"""
    offenders = [fence for fence in _bash_fences() if "$(" in fence]
    assert offenders == []


def test_hcd_vl_002_no_content_flags_in_bash_fences() -> None:
    """HCD-VL-002：交班內容 flag 不得出現在 bash 區塊，內容一律走 --from-file 的 JSON 檔。"""
    hits = [
        flag
        for fence in _bash_fences()
        for flag in _CONTENT_FLAGS
        if re.search(rf"{re.escape(flag)}(?![\w-])", fence)
    ]
    assert hits == []


def test_hcd_vl_003_exactly_one_from_file_write_line() -> None:
    """HCD-VL-003：bash 區塊中恰好一行是 `handover write --from-file "<FILE>"`。"""
    lines = [line.strip() for fence in _bash_fences() for line in fence.splitlines()]
    assert lines.count(_WRITE_LINE) == 1
