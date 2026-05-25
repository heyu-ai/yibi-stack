"""BHAUDIT-ST / BHAUDIT-CV transcript parser 測試。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tasks.bash_hygiene_audit.models import Verdict
from tasks.bash_hygiene_audit.transcript import (
    TranscriptBlockEvent,
    _cmd_hash,
    _parse_hook_reason,
    scan_project_transcripts,
    transcripts_to_audit_records,
)


def _make_transcript_lines(events: list[dict[str, object]]) -> str:
    """建立最小化 transcript JSONL，每個 dict 是一個 message。"""
    return "\n".join(json.dumps(e) for e in events) + "\n"


def _bash_tool_use_msg(cmd: str, ts: str = "2026-05-25T10:00:00.000Z") -> dict[str, object]:
    return {
        "timestamp": ts,
        "message": {
            "role": "assistant",
            "usage": {"output_tokens": 100, "input_tokens": 10},
            "content": [
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "id": "tool_1",
                    "input": {"command": cmd},
                }
            ],
        },
    }


def _hook_block_msg(ts: str = "2026-05-25T10:00:01.000Z") -> dict[str, object]:
    return {
        "timestamp": ts,
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tool_1",
                    "is_error": True,
                    "content": "PreToolUse:Bash hook error: [bash-ap2-check.py]: Em dash detected",
                }
            ],
        },
    }


def _non_hook_error_msg() -> dict[str, object]:
    return {
        "timestamp": "2026-05-25T10:00:02.000Z",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "is_error": True,
                    "content": "<tool_use_error>File not read yet.</tool_use_error>",
                }
            ],
        },
    }


class TestParseHookReason:
    def test_bhaudit_cv_001_ap2_unicode(self) -> None:
        """BHAUDIT-CV-001: 包含 'unicode' 的訊息回傳 ap2-unicode。"""
        assert _parse_hook_reason("ap2 unicode block") == "ap2-unicode"

    def test_bhaudit_cv_002_ap1_block(self) -> None:
        """BHAUDIT-CV-002: 包含 'ap1' 的訊息回傳 ap1-block。"""
        assert _parse_hook_reason("ap1 check failed") == "ap1-block"

    def test_bhaudit_cv_003_unknown_fallback(self) -> None:
        """BHAUDIT-CV-003: 無法識別的訊息回傳 unknown。"""
        assert _parse_hook_reason("some random error") == "unknown"


class TestCmdHash:
    def test_bhaudit_cv_004_hash_length(self) -> None:
        """BHAUDIT-CV-004: hash 固定為 16 字元十六進位。"""
        h = _cmd_hash("echo test")
        assert len(h) == 16
        assert h.isalnum()

    def test_bhaudit_cv_005_same_cmd_same_hash(self) -> None:
        """BHAUDIT-CV-005: 相同指令產生相同 hash。"""
        assert _cmd_hash("ls -la") == _cmd_hash("ls -la")

    def test_bhaudit_cv_006_diff_cmd_diff_hash(self) -> None:
        """BHAUDIT-CV-006: 不同指令產生不同 hash。"""
        assert _cmd_hash("ls -la") != _cmd_hash("ls -lb")


class TestScanProjectTranscripts:
    def test_bhaudit_st_001_finds_hook_block(self, tmp_path: Path) -> None:
        """BHAUDIT-ST-001: 找到 hook block tool_result 並產出 TranscriptBlockEvent。"""
        session_dir = tmp_path / "-Users-howie-test-repo"
        session_dir.mkdir(parents=True)
        transcript = session_dir / "aaaa-1111.jsonl"
        cmd = "echo 'test — em dash'"
        lines = _make_transcript_lines(
            [_bash_tool_use_msg(cmd), _hook_block_msg()]
        )
        transcript.write_text(lines, encoding="utf-8")

        events = scan_project_transcripts(
            project_slug="-Users-howie-test-repo",
            since_days=9999,
            projects_dir=tmp_path,
        )

        assert len(events) == 1
        e = events[0]
        assert e.session_id == "aaaa-1111"
        assert e.command_preview == cmd[:120]
        assert e.command_hash == _cmd_hash(cmd)
        assert e.block_reason == "ap2-unicode"

    def test_bhaudit_eg_001_missing_project_dir(self, tmp_path: Path) -> None:
        """BHAUDIT-EG-001: project 目錄不存在時 RuntimeError。"""
        with pytest.raises(RuntimeError, match="找不到 project transcript 目錄"):
            scan_project_transcripts(
                project_slug="-nonexistent",
                since_days=9999,
                projects_dir=tmp_path,
            )

    def test_bhaudit_st_002_skip_non_hook_error(self, tmp_path: Path) -> None:
        """BHAUDIT-ST-002: is_error=True 但非 hook block 訊息應跳過。"""
        session_dir = tmp_path / "-Users-howie-test-repo"
        session_dir.mkdir(parents=True)
        transcript = session_dir / "bbbb-2222.jsonl"
        lines = _make_transcript_lines(
            [_bash_tool_use_msg("ls"), _non_hook_error_msg()]
        )
        transcript.write_text(lines, encoding="utf-8")

        events = scan_project_transcripts(
            project_slug="-Users-howie-test-repo",
            since_days=9999,
            projects_dir=tmp_path,
        )
        assert len(events) == 0

    def test_bhaudit_st_003_empty_dir(self, tmp_path: Path) -> None:
        """BHAUDIT-ST-003: 目錄存在但無 .jsonl 檔 → 空列表。"""
        session_dir = tmp_path / "-Users-howie-empty"
        session_dir.mkdir(parents=True)

        events = scan_project_transcripts(
            project_slug="-Users-howie-empty",
            since_days=9999,
            projects_dir=tmp_path,
        )
        assert events == []


class TestTranscriptsToAuditRecords:
    def test_bhaudit_cv_007_field_mapping(self) -> None:
        """BHAUDIT-CV-007: TranscriptBlockEvent 欄位正確對應到 AuditRecord。"""
        event = TranscriptBlockEvent(
            session_id="sess-abc",
            ts="2026-05-25T10:00:00Z",
            command_preview="echo test",
            command_hash="deadbeef12345678",
            block_reason="ap2-unicode",
            wasted_ms=1500,
            wasted_tokens=300,
        )
        records = transcripts_to_audit_records([event])
        assert len(records) == 1
        r = records[0]
        assert r.session_id == "sess-abc"
        assert r.command_hash == "deadbeef12345678"
        assert r.block_reason == "ap2-unicode"
        assert r.verdict == Verdict.BLOCK
        assert r.exit_code == 2
        assert r.hook == "transcript"

    def test_bhaudit_cv_008_empty_events(self) -> None:
        """BHAUDIT-CV-008: 空列表輸入回傳空列表。"""
        assert transcripts_to_audit_records([]) == []
