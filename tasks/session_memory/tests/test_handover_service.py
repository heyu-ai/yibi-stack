"""測試 handover_service：write 自動帶 metadata、JSONL 鏡像同步。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tasks.session_memory.handover_service import read_recent, search_handovers, write_handover
from tasks.session_memory.models import SessionType


@pytest.fixture
def paths(tmp_path: Path) -> dict[str, Path]:
    return {
        "db": tmp_path / "handover.db",
        "jsonl": tmp_path / "handover.jsonl",
    }


class TestWriteHandover:
    def test_agents_st_010_write_inserts_and_mirrors(
        self, paths: dict[str, Path], monkeypatch
    ) -> None:
        """AGENTS-ST-010：write 同時寫 SQLite 與 JSONL 鏡像。"""
        monkeypatch.setenv("AGENT_ACCOUNT", "claude-pro")

        record = write_handover(
            session_type=SessionType.debug,
            topic="test topic",
            summary="test summary",
            db_path=paths["db"],
            jsonl_path=paths["jsonl"],
        )

        # SQLite
        rows = read_recent(last=1, db_path=paths["db"])
        assert len(rows) == 1
        assert rows[0]["id"] == record.id
        assert rows[0]["subscription_account"] == "claude-pro"

        # JSONL 鏡像
        lines = paths["jsonl"].read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        mirror = json.loads(lines[0])
        assert mirror["id"] == record.id
        assert mirror["session_type"] == "debug"

    def test_agents_vl_002_empty_topic_raises(self, paths: dict[str, Path]) -> None:
        """AGENTS-VL-002：topic 為空字串應 raise。"""
        with pytest.raises(ValueError):
            write_handover(
                session_type=SessionType.admin,
                topic="  ",
                summary="ok",
                db_path=paths["db"],
                jsonl_path=paths["jsonl"],
            )

    def test_agents_vl_003_empty_summary_raises(self, paths: dict[str, Path]) -> None:
        """AGENTS-VL-003：summary 為空字串應 raise。"""
        with pytest.raises(ValueError):
            write_handover(
                session_type=SessionType.admin,
                topic="t",
                summary="",
                db_path=paths["db"],
                jsonl_path=paths["jsonl"],
            )

    def test_agents_st_011_metadata_autofill(self, paths: dict[str, Path], monkeypatch) -> None:
        """AGENTS-ST-011：未提供 device/account/project 時自動 detect 填入。"""
        monkeypatch.setenv("AGENT_ACCOUNT", "test-account")
        with (
            patch("tasks.session_memory.handover_service.detect_device", return_value="test-dev"),
            patch("tasks.session_memory.handover_service.detect_project", return_value="test-proj"),
            patch("tasks.session_memory.handover_service.detect_branch", return_value="main"),
        ):
            record = write_handover(
                session_type=SessionType.discussion,
                topic="t",
                summary="s",
                db_path=paths["db"],
                jsonl_path=paths["jsonl"],
            )

        assert record.device == "test-dev"
        assert record.project == "test-proj"
        assert record.branch == "main"
        assert record.subscription_account == "test-account"

    def test_agents_st_012_explicit_override_metadata(self, paths: dict[str, Path]) -> None:
        """AGENTS-ST-012：明確提供 device/account 時覆蓋自動偵測。"""
        record = write_handover(
            session_type=SessionType.admin,
            topic="t",
            summary="s",
            device="override-dev",
            account="override-acct",
            project="override-proj",
            branch="override-branch",
            db_path=paths["db"],
            jsonl_path=paths["jsonl"],
        )
        assert record.device == "override-dev"
        assert record.subscription_account == "override-acct"
        assert record.project == "override-proj"
        assert record.branch == "override-branch"


class TestSearch:
    def test_agents_st_013_search_via_service(self, paths: dict[str, Path]) -> None:
        """AGENTS-ST-013：search_handovers 能從 db 找到剛寫入的資料。"""
        write_handover(
            session_type=SessionType.debug,
            topic="flight parser bug",
            summary="nom parsing fix",
            tags=["parser"],
            db_path=paths["db"],
            jsonl_path=paths["jsonl"],
        )

        rows = search_handovers(query="parser", db_path=paths["db"])
        assert len(rows) == 1
        assert "parser" in rows[0]["topic"]
