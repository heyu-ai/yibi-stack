"""plugins/dev-cycle/commands/handover.md 的指令區塊守護測試（AC-5）。

/handover 把交班內容寫進 JSON 檔，Bash 指令列只剩檔案路徑：內容放在指令列時，會被其他 repo 的
permission deny 規則（例如 `Bash(uv run --directory * alembic upgrade*)`）當成指令比對；
`$(...)` 則會被部分 repo 的 PreToolUse hook 擋下。這裡鎖住文件的 bash 區塊不得退回舊寫法。

Step 2 的錯誤分流依 CLI 的 stderr 文字判斷，所以部分測試（HCD-VL-007／008）會以真實
`write_handover` 實跑 `handover write`（DB／JSONL 導到 tmp），確認文件引用的訊息真的會出現，
而不只比對原始碼字串。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tasks.mycelium.tests._handover_lock import (
    LOCK_STAGES,
    assert_clean_lock_failure,
    run_handover_write_under_lock,
)

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
    """取出以 `heading` 開頭（必須位於行首）的段落，直到下一個 `## ` 標題為止。"""
    text = HANDOVER_DOC.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(heading)}", text, re.M)
    assert match is not None, f"{HANDOVER_DOC} 找不到段落 {heading!r}，解析前提不成立"
    start = match.start()
    end = text.find("\n## ", match.end())
    return text[start : end if end != -1 else len(text)]


def _bullet(section: str, marker: str) -> str:
    """取出含 `marker` 的那一個頂層 bullet（從 `- ` 行到下一個 `- ` 行或空行為止）。"""
    lines = section.splitlines()
    hit = next((i for i, line in enumerate(lines) if marker in line), None)
    assert hit is not None, f"段落中找不到 {marker!r}，解析前提不成立"
    start = next((i for i in range(hit, -1, -1) if lines[i].startswith("- ")), None)
    assert start is not None, f"{marker!r} 不在任何頂層 bullet 內，解析前提不成立"
    end = start + 1
    while end < len(lines) and lines[end].strip() and not lines[end].startswith("- "):
        end += 1
    return "\n".join(lines[start:end])


def _sub_bullet(bullet: str, marker: str) -> str:
    """取出頂層 bullet 內以 `marker` 開頭的那一個子 bullet（`  - ` 行連同其續行）。

    `marker` 必須出現在子 bullet 的第一行；續行是縮排比 `  - ` 更深的行。
    """
    lines = bullet.splitlines()
    hits = [i for i, line in enumerate(lines) if line.startswith("  - ") and marker in line]
    assert len(hits) == 1, f"應恰有一個以 {marker!r} 開頭的子 bullet，實際 {len(hits)} 個"
    end = hits[0] + 1
    while end < len(lines) and lines[end].startswith("    "):
        end += 1
    return "\n".join(lines[hits[0] : end])


def _source(module_file: str | None) -> str:
    assert module_file is not None
    return Path(module_file).read_text(encoding="utf-8")


# 「重跑」只允許出現在「不要重跑」與其說明括號「（重跑會再寫一筆…）」中，其餘都視為要求重跑
_UNNEGATED_RERUN = re.compile(r"(?<!不要)(?<!（)重跑")


def test_hcd_vl_004_backup_failure_must_not_retry() -> None:
    """HCD-VL-004：Step 2 對「DB 資料已保存」有專屬處理、禁止重跑，且結束指令、跳過 Step 3。"""
    from tasks.mycelium import handover_service

    message = "DB 資料已保存，但 JSONL 備份寫入失敗"
    assert message in _source(handover_service.__file__), (
        "handover_service 的備份失敗訊息已改，文件引用需同步"
    )
    branch = _bullet(_section("## Step 2"), message)
    assert "**不要重跑**" in branch
    assert "可重跑" not in branch
    assert _UNNEGATED_RERUN.search(branch) is None
    assert "跳過 Step 3" in branch
    # JSONL 本來就缺這一筆，不能叫使用者去那裡找；要回報 stderr 裡的記錄 id
    assert "handover.jsonl" not in branch
    assert "id=" in branch


def test_hcd_vl_005_step3_compares_value_after_equals() -> None:
    """HCD-VL-005：Step 3 以 ✓ 行判定成功，topic 只比 `=` 之後的值，不符時不重跑。"""
    from tasks.mycelium import cli as mycelium_cli

    cli_src = _source(mycelium_cli.__file__)
    # 鎖住文件所描述的 CLI 輸出格式
    assert 'click.echo(f"✓ handover 已寫入：{record.id}")' in cli_src
    assert 'click.echo(f"  topic   = {record.topic}")' in cli_src

    step3 = _section("## Step 3")
    assert "`✓ handover 已寫入：<id>`" in step3
    assert "`=` 之後的值" in step3
    assert "首尾空白" in step3
    assert "第一行" in step3
    assert re.search(r"忽略[^。\n]*空白", step3), "Step 3 必須說明比對時忽略空白"
    # 不得要求把整行字面比對成 `topic =` / `topic   =`
    assert re.search(r"`\s*topic\s*=\s*`", step3) is None
    # [FAIL] 只由缺少 ✓ 行觸發，與 topic 無關
    fail_branch = _bullet(step3, "[FAIL]")
    assert "✓ handover 已寫入" in fail_branch
    assert "topic" not in fail_branch
    # topic 不符時交班已寫入：只能 [WARN]，不得重跑
    mismatch = _bullet(step3, "topic 不符")
    assert "[WARN]" in mismatch
    assert "**不要重跑**" in mismatch
    assert _UNNEGATED_RERUN.search(step3) is None


def test_hcd_vl_006_db_write_failure_must_not_edit_json() -> None:
    """HCD-VL-006：「交班記錄寫入失敗」有專屬分支，排在「其他情況」之前，且不得修改 JSON 檔。"""
    from tasks.mycelium import handover_service

    message = "交班記錄寫入失敗"
    assert message in _source(handover_service.__file__), (
        "handover_service 的 DB 寫入失敗訊息已改，文件引用需同步"
    )
    step2 = _section("## Step 2")
    branch = _bullet(step2, message)
    assert "**不要修改 JSON 檔**" in branch
    assert "[FAIL] handover write 執行失敗" in branch
    assert "跳過 Step 3" in branch
    assert step2.index(message) < step2.index("其他情況")


def _invoke_handover_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: dict[str, str]
) -> str:
    """以真實 write_handover 跑 `handover write --from-file`（DB／JSONL 導到 tmp），回傳輸出。"""
    from click.testing import CliRunner

    from tasks.mycelium.cli import cli

    monkeypatch.setattr("tasks.mycelium.handover_service.HANDOVER_DB_PATH", tmp_path / "h.db")
    monkeypatch.setattr("tasks.mycelium.handover_service.HANDOVER_JSONL_PATH", tmp_path / "h.jsonl")
    path = tmp_path / "handover.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = CliRunner().invoke(cli, ["handover", "write", "--from-file", str(path)])
    assert result.exit_code == 1, result.output
    return result.output


def test_hcd_vl_007_other_cases_lists_blank_required_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HCD-VL-007：「其他情況」列出 topic／summary 為空白（CLI 實跑以「不可為空」拒絕）。"""
    output = _invoke_handover_write(
        tmp_path, monkeypatch, {"session_type": "debug", "topic": " ", "summary": "s"}
    )
    assert "topic 不可為空" in output
    assert "topic／summary 為空白" in _bullet(_section("## Step 2"), "其他情況")


@pytest.mark.parametrize("stage", LOCK_STAGES)
def test_hcd_vl_008_db_locked_allows_exactly_one_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """HCD-VL-008：DB 被鎖住時只允許用同一個檔案重跑 Step 2 一次，仍失敗就停止並跳過 Step 3。

    重試的前提是「鎖定時什麼都沒寫出」，所以先在真實 SQLite 鎖定下實跑 CLI 確認這點，
    再檢查文件的分流文字。
    """
    result = run_handover_write_under_lock(tmp_path, monkeypatch, stage=stage)
    # 文件依這兩段 stderr 文字分流，且重試不得產生重複交班
    assert_clean_lock_failure(result)

    branch = _bullet(_section("## Step 2"), "交班記錄寫入失敗")
    assert "**不要修改 JSON 檔**" in branch
    # 鎖定分支：不另外等待，用同一個檔案只重跑一次，成功就照常進入 Step 3
    retry = _sub_bullet(branch, "database is locked")
    assert "同一個檔案" in retry
    assert "**一次**" in retry
    assert "等幾秒" not in retry
    assert "照常進入 Step 3" in retry
    assert "不要進入 Step 3" not in retry
    # 重跑的結果要從頭重新分流：DB 已寫入但 JSONL 失敗時走 [WARN] 分支，不是 [FAIL]
    assert "重新判斷" in retry
    assert "DB 資料已保存，但 JSONL 備份寫入失敗" in retry
    assert "[WARN]" in retry
    # 停止分支：其他原因，或重試後仍失敗 → [FAIL] 並跳過 Step 3
    stop = _sub_bullet(branch, "其他原因")
    assert "其他原因" in stop and "重試後仍失敗" in stop
    assert "交班記錄寫入失敗" in stop
    assert "[FAIL] handover write 執行失敗" in stop
    assert "跳過 Step 3" in stop
