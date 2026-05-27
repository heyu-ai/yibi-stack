"""NIGHTLY-extractor tests."""

from __future__ import annotations

import json
import time
from pathlib import Path

from tasks.nightly_agent.extractor import TranscriptExtractor, _extract_text, _parse_entry


def make_user_entry(
    session_id: str = "s1", text: str = "hello", ts: str = "2026-05-27T03:00:00.000Z"
) -> dict[str, object]:
    return {
        "type": "user",
        "sessionId": session_id,
        "timestamp": ts,
        "cwd": "/Users/howie/project",
        "gitBranch": "main",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
        },
    }


def make_assistant_entry(
    session_id: str = "s1", text: str = "reply", ts: str = "2026-05-27T03:00:01.000Z"
) -> dict[str, object]:
    return {
        "type": "assistant",
        "sessionId": session_id,
        "timestamp": ts,
        "cwd": "/Users/howie/project",
        "gitBranch": "main",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    }


def make_jsonl(entries: list[dict[str, object]]) -> str:
    return "\n".join(json.dumps(e) for e in entries) + "\n"


class TestExtractText:
    def test_string_content(self) -> None:
        assert _extract_text("hello") == "hello"

    def test_list_text_blocks(self) -> None:
        result = _extract_text([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}])
        assert "a" in result and "b" in result

    def test_non_text_block_skipped(self) -> None:
        result = _extract_text([{"type": "thinking", "thinking": "hmm"}])
        assert result == ""

    def test_empty_list(self) -> None:
        assert _extract_text([]) == ""


class TestParseEntry:
    def test_user_entry_parsed(self) -> None:
        entry = _parse_entry(make_user_entry(text="test question"))
        assert entry is not None
        assert entry.entry_type == "user"
        assert "test question" in entry.text_content

    def test_assistant_entry_parsed(self) -> None:
        entry = _parse_entry(make_assistant_entry(text="test reply"))
        assert entry is not None
        assert entry.entry_type == "assistant"

    def test_metadata_entry_skipped(self) -> None:
        obj: dict[str, object] = {
            "type": "agent-setting",
            "agentSetting": "claude",
            "sessionId": "s1",
        }
        assert _parse_entry(obj) is None

    def test_empty_text_skipped(self) -> None:
        entry = make_assistant_entry(text="   ")
        assert _parse_entry(entry) is None


class TestTranscriptExtractor:
    def test_recent_file_included(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project-slug"
        project_dir.mkdir()
        jsonl_file = project_dir / "session1.jsonl"
        jsonl_file.write_text(make_jsonl([make_user_entry(), make_assistant_entry()]))

        extractor = TranscriptExtractor(lookback_hours=24, projects_dir=tmp_path)
        sessions = extractor.extract()
        assert len(sessions) == 1
        assert len(sessions[0].entries) == 2

    def test_old_file_excluded(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project-slug"
        project_dir.mkdir()
        jsonl_file = project_dir / "old_session.jsonl"
        jsonl_file.write_text(make_jsonl([make_user_entry()]))
        # Set mtime to 30 hours ago
        old_mtime = time.time() - 30 * 3600
        import os

        os.utime(jsonl_file, (old_mtime, old_mtime))

        extractor = TranscriptExtractor(lookback_hours=24, projects_dir=tmp_path)
        sessions = extractor.extract()
        assert len(sessions) == 0

    def test_session_id_extracted(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        jsonl_file = project_dir / "abc123.jsonl"
        jsonl_file.write_text(make_jsonl([make_user_entry(session_id="real-session-id")]))
        extractor = TranscriptExtractor(lookback_hours=24, projects_dir=tmp_path)
        sessions = extractor.extract()
        assert sessions[0].session_id == "real-session-id"

    def test_empty_file_skipped(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        (project_dir / "empty.jsonl").write_text("")
        extractor = TranscriptExtractor(lookback_hours=24, projects_dir=tmp_path)
        assert extractor.extract() == []

    def test_invalid_json_lines_skipped(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        valid = (
            '{"type": "user", "message": {"role": "user",'
            ' "content": [{"type": "text", "text": "hi"}]},'
            ' "sessionId": "x", "timestamp": "t", "cwd": "/", "gitBranch": "main"}'
        )
        content = valid + "\nNOT_JSON_LINE\n"
        (project_dir / "mixed.jsonl").write_text(content)
        extractor = TranscriptExtractor(lookback_hours=24, projects_dir=tmp_path)
        sessions = extractor.extract()
        assert len(sessions) == 1
        assert len(sessions[0].entries) == 1
