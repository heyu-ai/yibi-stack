"""測試 retrospective_service：write 自動帶 metadata、token 用量整合、JSONL 鏡像同步。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tasks.mycelium.models import TokenUsageSource
from tasks.mycelium.retrospective_service import (
    read_recent_retrospectives,
    search_retrospectives,
    write_retrospective,
)
from tasks.mycelium.token_usage_service import TokenUsageReport


@pytest.fixture
def paths(tmp_path: Path) -> dict[str, Path]:
    return {
        "db": tmp_path / "handover.db",
        "jsonl": tmp_path / "retrospectives.jsonl",
    }


class TestWriteRetrospective:
    def test_retro_st_001_write_inserts_and_mirrors(
        self, paths: dict[str, Path], monkeypatch
    ) -> None:
        """RETRO-ST-001：write 同時寫 SQLite 與 JSONL 鏡像。"""
        monkeypatch.setenv("AGENT_ACCOUNT", "claude-pro")

        record = write_retrospective(
            pr_number=205,
            topic="Retro: PR #205 - fix bug",
            summary="test summary",
            db_path=paths["db"],
            jsonl_path=paths["jsonl"],
        )

        rows = read_recent_retrospectives(last=1, db_path=paths["db"])
        assert len(rows) == 1
        assert rows[0]["id"] == record.id
        assert rows[0]["pr_number"] == 205
        assert rows[0]["subscription_account"] == "claude-pro"

        lines = paths["jsonl"].read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        mirror = json.loads(lines[0])
        assert mirror["id"] == record.id
        assert mirror["pr_number"] == 205

    def test_retro_vl_001_empty_topic_raises(self, paths: dict[str, Path]) -> None:
        """RETRO-VL-001：topic 為空字串應 raise。"""
        with pytest.raises(ValueError):
            write_retrospective(
                pr_number=1,
                topic="  ",
                summary="ok",
                db_path=paths["db"],
                jsonl_path=paths["jsonl"],
            )

    def test_retro_vl_002_empty_summary_raises(self, paths: dict[str, Path]) -> None:
        """RETRO-VL-002：summary 為空字串應 raise。"""
        with pytest.raises(ValueError):
            write_retrospective(
                pr_number=1,
                topic="t",
                summary="",
                db_path=paths["db"],
                jsonl_path=paths["jsonl"],
            )

    def test_retro_st_002_metadata_autofill(self, paths: dict[str, Path], monkeypatch) -> None:
        """RETRO-ST-002：未提供 device/account/project 時自動 detect 填入。"""
        monkeypatch.setenv("AGENT_ACCOUNT", "test-account")
        with (
            patch("tasks.mycelium.retrospective_service.detect_device", return_value="test-dev"),
            patch("tasks.mycelium.retrospective_service.detect_project", return_value="test-proj"),
            patch("tasks.mycelium.retrospective_service.detect_branch", return_value="main"),
        ):
            record = write_retrospective(
                pr_number=1,
                topic="t",
                summary="s",
                db_path=paths["db"],
                jsonl_path=paths["jsonl"],
            )

        assert record.device == "test-dev"
        assert record.project == "test-proj"
        assert record.branch == "main"
        assert record.subscription_account == "test-account"

    def test_retro_st_003_explicit_override_metadata(self, paths: dict[str, Path]) -> None:
        """RETRO-ST-003：明確提供 device/account 時覆蓋自動偵測。"""
        record = write_retrospective(
            pr_number=1,
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

    def test_retro_st_006_branch_detected_from_working_dir_not_process_cwd(
        self, paths: dict[str, Path], tmp_path: Path
    ) -> None:
        """RETRO-ST-006：detect_branch 要用 `--workdir` 解析出的目錄，不是行程當下的 cwd。

        SKILL.md 的 Step 4 用 `uv run --directory "$SKILL_REPO"` 執行（子行程 cwd
        變成 SKILL_REPO），同時傳 `--workdir "$REAL_WORKDIR"`（實際要回顧的 PR
        worktree）——如果 detect_branch() 沒有明確傳入 effective_dir，會偵測到
        SKILL_REPO 當下所在的 branch，不是 REAL_WORKDIR 的 branch。
        """
        fake_workdir = tmp_path / "some-other-worktree"
        fake_workdir.mkdir()

        with patch("tasks.mycelium.retrospective_service.detect_branch") as mock_detect_branch:
            mock_detect_branch.return_value = "feature-branch"
            write_retrospective(
                pr_number=1,
                topic="t",
                summary="s",
                working_dir=str(fake_workdir),
                db_path=paths["db"],
                jsonl_path=paths["jsonl"],
            )

        mock_detect_branch.assert_called_once_with(fake_workdir.resolve())


class TestAutoTokenUsage:
    """write_retrospective(auto_token_usage=True) 在三種 compute 狀態下都不能 raise。"""

    def test_retro_tok_st_001_computed_populates_fields(self, paths: dict[str, Path]) -> None:
        """RETRO-TOK-ST-001：status=computed 時，8 個 token 欄位被填入。"""
        report = TokenUsageReport(
            status="computed",
            total_input_tokens=100,
            total_output_tokens=20,
            total_cache_read_tokens=5,
            total_cache_creation_tokens=3,
            total_cost_usd=0.01,
            by_model=[{"model": "claude-sonnet-5", "cost_usd": 0.01}],
            session_effort="high",
            optimization_notes=["[best-effort] 測試"],
        )
        with patch(
            "tasks.mycelium.token_usage_service.compute_token_usage_report",
            return_value=report,
        ):
            record = write_retrospective(
                pr_number=1,
                topic="t",
                summary="s",
                auto_token_usage=True,
                db_path=paths["db"],
                jsonl_path=paths["jsonl"],
            )

        assert record.token_input_tokens == 100
        assert record.token_total_cost_usd == 0.01
        assert record.session_effort == "high"
        assert record.token_usage_source is not None
        assert record.token_usage_source.value == "computed"

    def test_retro_tok_st_002_ambiguous_leaves_numeric_fields_none(
        self, paths: dict[str, Path]
    ) -> None:
        """RETRO-TOK-ST-002：status=ambiguous 時只設 token_usage_source，數值仍是 None。"""
        report = TokenUsageReport(status="ambiguous", warning="偵測到並行 session")
        with patch(
            "tasks.mycelium.token_usage_service.compute_token_usage_report",
            return_value=report,
        ):
            record = write_retrospective(
                pr_number=1,
                topic="t",
                summary="s",
                auto_token_usage=True,
                db_path=paths["db"],
                jsonl_path=paths["jsonl"],
            )

        assert record.token_input_tokens is None
        assert record.token_total_cost_usd is None
        assert record.token_usage_source is not None
        assert record.token_usage_source.value == "ambiguous"

    def test_retro_tok_eg_001_compute_raises_does_not_block_write(
        self, paths: dict[str, Path]
    ) -> None:
        """RETRO-TOK-EG-001：token 用量計算本身 raise 例外時，write_retrospective 仍成功寫入。"""
        with patch(
            "tasks.mycelium.token_usage_service.compute_token_usage_report",
            side_effect=RuntimeError("boom"),
        ):
            record = write_retrospective(
                pr_number=1,
                topic="t",
                summary="s",
                auto_token_usage=True,
                db_path=paths["db"],
                jsonl_path=paths["jsonl"],
            )

        assert record.token_usage_source == TokenUsageSource.unavailable
        rows = read_recent_retrospectives(last=1, db_path=paths["db"])
        assert rows[0]["id"] == record.id

    def test_retro_tok_st_003_flag_off_skips_computation(self, paths: dict[str, Path]) -> None:
        """RETRO-TOK-ST-003：auto_token_usage=False（預設）時完全不呼叫計算函式。"""
        with patch("tasks.mycelium.token_usage_service.compute_token_usage_report") as mock_compute:
            record = write_retrospective(
                pr_number=1,
                topic="t",
                summary="s",
                db_path=paths["db"],
                jsonl_path=paths["jsonl"],
            )

        mock_compute.assert_not_called()
        assert record.token_usage_source is None


class TestSearchRetrospectives:
    def test_retro_st_004_search_by_pr_number_exact(self, paths: dict[str, Path]) -> None:
        """RETRO-ST-004：search_retrospectives(pr_number=...) 精確匹配。"""
        write_retrospective(
            pr_number=205, topic="a", summary="s", db_path=paths["db"], jsonl_path=paths["jsonl"]
        )
        write_retrospective(
            pr_number=2005, topic="b", summary="s", db_path=paths["db"], jsonl_path=paths["jsonl"]
        )

        rows = search_retrospectives(pr_number=205, db_path=paths["db"])
        assert len(rows) == 1
        assert rows[0]["pr_number"] == 205

    def test_retro_st_005_search_returns_empty_when_no_match(self, paths: dict[str, Path]) -> None:
        """RETRO-ST-005：找不到對應 pr_number 時回傳空 list（不 raise）。"""
        rows = search_retrospectives(pr_number=999, db_path=paths["db"])
        assert rows == []
