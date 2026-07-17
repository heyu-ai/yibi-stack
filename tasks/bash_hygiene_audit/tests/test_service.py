"""BHAUDIT-ST / BHAUDIT-DT service 層測試。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from tasks.bash_hygiene_audit.models import AuditRecord
from tasks.bash_hygiene_audit.service import (
    _find_log_dir,
    _find_log_path,
    compute_repeats,
    compute_stats,
    count_log_lines,
    read_log,
)


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


class TestFindLogPath:
    def test_bhaudit_st_017_worktree_resolves_to_main_repo(self, tmp_path: Path) -> None:
        """BHAUDIT-ST-017: _find_log_dir 用 --git-common-dir parent，不用 --show-toplevel。

        在 linked worktree 裡，`--show-toplevel` 回傳 worktree 路徑；
        `--git-common-dir` 指向主 repo 的 .git 目錄，其 parent 才是真正的 repo root。
        _find_log_dir 負責這一層解析，直接測它而非測 _find_log_path 鏈的末端，
        以避免 _find_log_paths 的 is_dir() 守衛（目錄不存在就回 None）遮蔽路徑邏輯。
        """
        fake_git_dir = tmp_path / ".git"
        fake_git_dir.mkdir()
        mock_run = MagicMock()
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = str(fake_git_dir) + "\n"
        with patch("tasks.bash_hygiene_audit.service.subprocess.run", mock_run):
            result = _find_log_dir()
        assert result == tmp_path / ".runtime" / "logs"
        called_args = mock_run.call_args[0][0]
        assert "--git-common-dir" in called_args
        assert "--show-toplevel" not in called_args

    def test_bhaudit_st_018_git_nonzero_returns_none(self) -> None:
        """BHAUDIT-ST-018: git 指令回傳非零 exit code 時 _find_log_path 回傳 None，不拋例外。"""
        mock_run = MagicMock()
        mock_run.return_value.returncode = 128
        with patch("tasks.bash_hygiene_audit.service.subprocess.run", mock_run):
            assert _find_log_path() is None


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


def _make_block_record(
    session_id: str,
    command_hash: str,
    ts: str = "2026-05-25T00:00:00Z",
    block_reason: str = "ap2-unicode",
    cmd_snippet: str = "echo test",
) -> AuditRecord:
    return AuditRecord.model_validate(
        {
            "ts": ts,
            "hook": "ap2",
            "hook_version": "2",
            "exit_code": 2,
            "verdict": "block",
            "block_reason": block_reason,
            "cmd_snippet": cmd_snippet,
            "command_hash": command_hash,
            "session_id": session_id,
        }
    )


def _make_allow_record(session_id: str, command_hash: str = "abc") -> AuditRecord:
    return AuditRecord.model_validate(
        {
            "ts": "2026-05-25T00:00:00Z",
            "hook": "ap1",
            "hook_version": "2",
            "exit_code": 0,
            "verdict": "allow",
            "cmd_snippet": "ls -la",
            "command_hash": command_hash,
            "session_id": session_id,
        }
    )


class TestComputeRepeats:
    def test_bhaudit_dt_005_basic_repeat(self) -> None:
        """BHAUDIT-DT-005: 同 session 同 hash block 3 次 → 1 個 RepeatEvent (count=3)。"""
        records = [
            _make_block_record("sess1", "hash1", ts="2026-05-25T00:00:00Z"),
            _make_block_record("sess1", "hash1", ts="2026-05-25T00:01:00Z"),
            _make_block_record("sess1", "hash1", ts="2026-05-25T00:02:00Z"),
        ]
        s = compute_repeats(records)
        assert s.total_blocks == 3
        assert s.repeated_blocks == 3
        assert s.unique_repeat_events == 1
        assert len(s.top_offenders) == 1
        assert s.top_offenders[0].count == 3
        assert s.top_offenders[0].estimated_wasted_tokens == 2 * 1500

    def test_bhaudit_dt_006_cross_session_not_repeat(self) -> None:
        """BHAUDIT-DT-006: 同 hash 但不同 session 不算重複。"""
        records = [
            _make_block_record("sess1", "hash1"),
            _make_block_record("sess2", "hash1"),
        ]
        s = compute_repeats(records)
        assert s.unique_repeat_events == 0
        assert s.repeated_blocks == 0

    def test_bhaudit_dt_007_top_n_sorting(self) -> None:
        """BHAUDIT-DT-007: top_offenders 按 count 降序排列。"""
        records = [
            # hash2: 3 次
            _make_block_record("s1", "hash2"),
            _make_block_record("s1", "hash2"),
            _make_block_record("s1", "hash2"),
            # hash1: 2 次
            _make_block_record("s1", "hash1"),
            _make_block_record("s1", "hash1"),
        ]
        s = compute_repeats(records, top_n=5)
        assert s.top_offenders[0].command_hash == "hash2"
        assert s.top_offenders[0].count == 3
        assert s.top_offenders[1].command_hash == "hash1"
        assert s.top_offenders[1].count == 2

    def test_bhaudit_eg_001_empty_records(self) -> None:
        """BHAUDIT-EG-001: 空列表回傳 zero RepeatStats。"""
        s = compute_repeats([])
        assert s.total_blocks == 0
        assert s.unique_repeat_events == 0
        assert s.repeat_rate == 0.0

    def test_bhaudit_eg_002_only_allow_records(self) -> None:
        """BHAUDIT-EG-002: 全 allow 時 total_blocks=0，無重複事件。"""
        records = [_make_allow_record("s1"), _make_allow_record("s1")]
        s = compute_repeats(records)
        assert s.total_blocks == 0
        assert s.unique_repeat_events == 0

    def test_bhaudit_dt_008_token_estimate_respected(self) -> None:
        """BHAUDIT-DT-008: token_per_repeat_estimate 正確套用到 extra blocks。"""
        records = [
            _make_block_record("s1", "h1"),
            _make_block_record("s1", "h1"),
        ]
        s = compute_repeats(records, token_per_repeat_estimate=500)
        assert s.top_offenders[0].estimated_wasted_tokens == 500  # (2-1) * 500

    def test_bhaudit_dt_009_wasted_ms_calculation(self) -> None:
        """BHAUDIT-DT-009: estimated_wasted_ms = last_ts - first_ts 的毫秒差。"""
        records = [
            _make_block_record("s1", "h1", ts="2026-05-25T10:00:00Z"),
            _make_block_record("s1", "h1", ts="2026-05-25T10:00:30Z"),
        ]
        s = compute_repeats(records)
        assert s.top_offenders[0].estimated_wasted_ms == 30000  # 30 秒

    def test_bhaudit_dt_010_no_session_id_excluded(self) -> None:
        """BHAUDIT-DT-010: session_id 為 None 的 block 記錄不計入 repeat 分析。"""
        record = AuditRecord.model_validate(
            {
                "ts": "2026-05-25T00:00:00Z",
                "hook": "ap1",
                "hook_version": "2",
                "exit_code": 2,
                "verdict": "block",
                "cmd_snippet": "test",
                "command_hash": "hash1",
                "session_id": None,
            }
        )
        records = [record, record]
        s = compute_repeats(records)
        assert s.unique_repeat_events == 0
