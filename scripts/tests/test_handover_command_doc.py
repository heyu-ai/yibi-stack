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


def _section(heading: str) -> str:
    text = HANDOVER_DOC.read_text(encoding="utf-8")
    start = text.find(heading)
    assert start != -1, f"{HANDOVER_DOC} 找不到段落 {heading!r}，解析前提不成立"
    end = text.find("\n## ", start + len(heading))
    return text[start : end if end != -1 else len(text)]


def test_hcd_vl_004_backup_failure_must_not_retry() -> None:
    """HCD-VL-004：Step 2 對「DB 資料已保存」有專屬處理且禁止重跑，避免重複寫入交班。"""
    from tasks.mycelium import handover_service

    message = "DB 資料已保存，但 JSONL 備份寫入失敗"
    service_src = Path(handover_service.__file__).read_text(encoding="utf-8")
    assert message in service_src, "handover_service 的備份失敗訊息已改，文件引用需同步"
    step2 = _section("## Step 2")
    assert message in step2
    branch = next(line for line in step2.splitlines() if message in line)
    assert "不要重跑" in branch


def test_hcd_vl_005_step3_does_not_require_literal_topic_equals() -> None:
    """HCD-VL-005：Step 3 不得要求字面比對 `topic =`；CLI 實際輸出是對齊空白的 `topic   =`。"""
    step3 = _section("## Step 3")
    assert "`topic =`" not in step3
    assert "對齊" in step3
