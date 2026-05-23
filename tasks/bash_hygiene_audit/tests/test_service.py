"""BHAUDIT-ST / BHAUDIT-DT service 層測試。"""

from __future__ import annotations

import json
from pathlib import Path

from tasks.bash_hygiene_audit.models import AuditRecord
from tasks.bash_hygiene_audit.service import compute_stats, count_log_lines, read_log


def _make_jsonl(records: list[dict[str, object]]) -> str:
    return "\n".join(json.dumps(r) for r in records) + "\n"


def _base_record(
    verdict: str = "allow",
    hook: str = "ap1",
    block_reason: str | None = None,
    duration_ms: int | None = None,
) -> dict[str, object]:
    return {
        "ts": "2026-05-21T00:00:00Z",
        "hook": hook,
        "hook_version": "2",
        "exit_code": 2 if verdict == "block" else 0,
        "verdict": verdict,
        "block_reason": block_reason,
        "cmd_snippet": "echo test",
        "command_hash": "abc123",
        "session_id": None,
        "duration_ms": duration_ms,
    }


class TestReadLog:
    def test_bhaudit_st_001_empty_file(self, tmp_path: Path) -> None:
        """BHAUDIT-ST-001: 空檔案回傳空列表。"""
        log_dir = tmp_path / ".runtime" / "logs"
        log_dir.mkdir(parents=True)
        log = log_dir / "bash-hygiene-audit.jsonl"
        log.write_text("")
        result = read_log(project_root=tmp_path, last=10)
        assert result == []

    def test_bhaudit_st_002_reads_records(self, tmp_path: Path) -> None:
        """BHAUDIT-ST-002: 正確讀取 JSONL 記錄。"""
        log_dir = tmp_path / ".runtime" / "logs"
        log_dir.mkdir(parents=True)
        log = log_dir / "bash-hygiene-audit.jsonl"
        log.write_text(
            _make_jsonl([_base_record(), _base_record("block", block_reason="ap2-unicode")])
        )
        result = read_log(last=10, project_root=tmp_path)
        assert len(result) == 2
        assert result[0].verdict == "allow"
        assert result[1].verdict == "block"

    def test_bhaudit_st_003_filter_hook(self, tmp_path: Path) -> None:
        """BHAUDIT-ST-003: hook 過濾正確。"""
        log_dir = tmp_path / ".runtime" / "logs"
        log_dir.mkdir(parents=True)
        log = log_dir / "bash-hygiene-audit.jsonl"
        log.write_text(_make_jsonl([_base_record(hook="ap1"), _base_record(hook="ap2")]))
        result = read_log(last=10, hook="ap2", project_root=tmp_path)
        assert len(result) == 1
        assert result[0].hook == "ap2"

    def test_bhaudit_st_004_last_truncates(self, tmp_path: Path) -> None:
        """BHAUDIT-ST-004: last 參數正確截斷最新 N 筆。"""
        log_dir = tmp_path / ".runtime" / "logs"
        log_dir.mkdir(parents=True)
        log = log_dir / "bash-hygiene-audit.jsonl"
        log.write_text(_make_jsonl([_base_record() for _ in range(5)]))
        result = read_log(last=3, project_root=tmp_path)
        assert len(result) == 3

    def test_bhaudit_st_005_skip_malformed_lines(self, tmp_path: Path) -> None:
        """BHAUDIT-ST-005: 格式錯誤的行被跳過，不中斷解析。"""
        log_dir = tmp_path / ".runtime" / "logs"
        log_dir.mkdir(parents=True)
        log = log_dir / "bash-hygiene-audit.jsonl"
        log.write_text("not-valid-json\n" + json.dumps(_base_record()) + "\n")
        result = read_log(last=10, project_root=tmp_path)
        assert len(result) == 1

    def test_bhaudit_st_006_count_log_lines(self, tmp_path: Path) -> None:
        """BHAUDIT-ST-006: count_log_lines 正確計算非空行數（忽略空行）。"""
        log_dir = tmp_path / ".runtime" / "logs"
        log_dir.mkdir(parents=True)
        log = log_dir / "bash-hygiene-audit.jsonl"
        log.write_text(json.dumps(_base_record()) + "\n" + json.dumps(_base_record()) + "\n\n")
        assert count_log_lines(project_root=tmp_path) == 2

    def test_bhaudit_st_007_count_log_lines_no_file(self, tmp_path: Path) -> None:
        """BHAUDIT-ST-007: log 不存在時 count_log_lines 回傳 0。"""
        assert count_log_lines(project_root=tmp_path) == 0


class TestComputeStats:
    def _make_records(
        self, verdicts: list[str], durations: list[int | None] | None = None
    ) -> list[AuditRecord]:
        if durations is None:
            durations = [None] * len(verdicts)
        return [
            AuditRecord.model_validate(
                {
                    **_base_record(verdict=v, duration_ms=d),
                    "block_reason": "ap2-unicode" if v == "block" else None,
                }
            )
            for v, d in zip(verdicts, durations, strict=True)
        ]

    def test_bhaudit_dt_001_all_allow(self) -> None:
        """BHAUDIT-DT-001: 全 allow 時 block_count=0。"""
        records = self._make_records(["allow", "allow"])
        s = compute_stats(records)
        assert s.total == 2
        assert s.allow_count == 2
        assert s.block_count == 0

    def test_bhaudit_dt_002_mixed(self) -> None:
        """BHAUDIT-DT-002: 混合 allow/block 計算正確。"""
        records = self._make_records(["allow", "block", "block"])
        s = compute_stats(records)
        assert s.allow_count == 1
        assert s.block_count == 2
        assert s.by_reason.get("ap2-unicode") == 2

    def test_bhaudit_dt_003_avg_duration(self) -> None:
        """BHAUDIT-DT-003: 有 duration_ms 時計算平均值。"""
        records = self._make_records(["allow", "allow"], durations=[10, 20])
        s = compute_stats(records)
        assert s.avg_duration_ms == 15.0

    def test_bhaudit_dt_004_empty_records(self) -> None:
        """BHAUDIT-DT-004: 空列表時所有計數為 0，avg_duration_ms 為 None。"""
        s = compute_stats([])
        assert s.total == 0
        assert s.avg_duration_ms is None
