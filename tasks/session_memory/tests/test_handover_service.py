"""測試 handover_service：write 自動帶 metadata、JSONL 鏡像同步。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tasks.session_memory.config import from_portable_path, to_portable_path
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


class TestPortablePaths:
    def test_agents_cv_010_to_portable_replaces_home(self) -> None:
        """AGENTS-CV-010：to_portable_path 將 $HOME 前綴轉為 ~/。"""
        home = str(Path.home())
        assert to_portable_path(f"{home}/foo/bar") == "~/foo/bar"

    def test_agents_cv_011_to_portable_exact_home(self) -> None:
        """AGENTS-CV-011：to_portable_path 對恰好是 $HOME 的路徑回傳 ~。"""
        assert to_portable_path(str(Path.home())) == "~"

    def test_agents_cv_012_to_portable_outside_home_unchanged(self) -> None:
        """AGENTS-CV-012：to_portable_path 對 $HOME 外的路徑不修改。"""
        assert to_portable_path("/var/log/syslog") == "/var/log/syslog"

    def test_agents_cv_013_from_portable_expands_tilde(self) -> None:
        """AGENTS-CV-013：from_portable_path 將 ~/... 展開為當前 home 絕對路徑。"""
        home = str(Path.home())
        assert from_portable_path("~/foo/bar") == f"{home}/foo/bar"

    def test_agents_cv_014_from_portable_tilde_only(self) -> None:
        """AGENTS-CV-014：from_portable_path 對單獨 ~ 回傳 $HOME。"""
        assert from_portable_path("~") == str(Path.home())

    def test_agents_cv_015_from_portable_absolute_unchanged(self) -> None:
        """AGENTS-CV-015：from_portable_path 對舊式絕對路徑原樣回傳（向後相容）。"""
        old_abs = "/Users/howie/Workspace/foo"
        assert from_portable_path(old_abs) == old_abs

    def test_agents_cv_016_roundtrip(self) -> None:
        """AGENTS-CV-016：to/from portable_path 互為反函式。"""
        original = str(Path.home() / "Workspace" / "project")
        assert from_portable_path(to_portable_path(original)) == original

    def test_agents_st_020_write_stores_portable_working_dir(self, paths: dict[str, Path]) -> None:
        """AGENTS-ST-020：write_handover 寫入的 working_dir 以 ~/... 格式儲存。"""
        record = write_handover(
            session_type=SessionType.admin,
            topic="t",
            summary="s",
            working_dir=str(Path.home() / "Workspace" / "test-proj"),
            db_path=paths["db"],
            jsonl_path=paths["jsonl"],
        )
        assert record.working_dir == "~/Workspace/test-proj"

    def test_agents_st_021_read_returns_expanded_working_dir(self, paths: dict[str, Path]) -> None:
        """AGENTS-ST-021：read_recent 回傳的 working_dir 已展開為絕對路徑。"""
        write_handover(
            session_type=SessionType.admin,
            topic="t",
            summary="s",
            working_dir=str(Path.home() / "Workspace" / "test-proj"),
            db_path=paths["db"],
            jsonl_path=paths["jsonl"],
        )
        rows = read_recent(last=1, db_path=paths["db"])
        assert rows[0]["working_dir"] == str(Path.home() / "Workspace" / "test-proj")

    def test_agents_st_022_last_files_portable(self, paths: dict[str, Path]) -> None:
        """AGENTS-ST-022：last_files 寫入時 tilde-encode、讀回時展開。"""
        home = Path.home()
        files = [str(home / "proj" / "foo.py"), str(home / "proj" / "bar.py")]
        write_handover(
            session_type=SessionType.sdd,
            topic="t",
            summary="s",
            last_files=files,
            db_path=paths["db"],
            jsonl_path=paths["jsonl"],
        )
        rows = read_recent(last=1, db_path=paths["db"])
        assert rows[0]["last_files"] == files  # 展開後與原始一致


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
