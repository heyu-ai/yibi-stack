"""測試 handover_service：write 自動帶 metadata、JSONL 鏡像同步。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tasks.mycelium.config import from_portable_path, to_portable_path
from tasks.mycelium.handover_service import read_recent, search_handovers, write_handover
from tasks.mycelium.models import SessionType


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
            patch("tasks.mycelium.handover_service.detect_device", return_value="test-dev"),
            patch("tasks.mycelium.handover_service.detect_project", return_value="test-proj"),
            patch("tasks.mycelium.handover_service.detect_branch", return_value="main"),
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

    def test_agents_st_030_project_inferred_from_working_dir(
        self, paths: dict[str, Path], tmp_path: Path
    ) -> None:
        """AGENTS-ST-030: 未傳 project 時從 working_dir basename 推導。

        防止 uv run --directory 造成 cwd 漂移導致 project 被錯誤記錄。
        此測試在舊版（detect_project() 不傳 cwd）會因 cwd 是 repo root 而失敗。
        """
        fake_workdir = tmp_path / "my-real-project"
        fake_workdir.mkdir()

        record = write_handover(
            session_type=SessionType.debug,
            topic="t",
            summary="s",
            working_dir=str(fake_workdir),
            db_path=paths["db"],
            jsonl_path=paths["jsonl"],
        )

        assert record.project == "my-real-project"

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

    def test_agents_cv_017_to_portable_sibling_prefix_unchanged(self) -> None:
        """AGENTS-CV-017：路徑前綴與 $HOME 字串相同但不在其下時原樣回傳（防止前綴誤匹配）。"""
        sibling = str(Path.home()) + "other/path"  # e.g. /Users/howieother/path
        assert to_portable_path(sibling) == sibling

    def test_agents_cv_013_from_portable_expands_tilde(self) -> None:
        """AGENTS-CV-013：from_portable_path 將 ~/... 展開為當前 home 絕對路徑。"""
        home = str(Path.home())
        assert from_portable_path("~/foo/bar") == f"{home}/foo/bar"

    def test_agents_cv_014_from_portable_tilde_only(self) -> None:
        """AGENTS-CV-014：from_portable_path 對單獨 ~ 回傳 $HOME。"""
        assert from_portable_path("~") == str(Path.home())

    def test_agents_cv_015_from_portable_absolute_unchanged(self) -> None:
        """AGENTS-CV-015：from_portable_path 對舊式絕對路徑原樣回傳（向後相容）。"""
        old_abs = "/var/log/old-absolute-path"  # 任何機器都不在 $HOME 下
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
        # JSONL 鏡像儲存 tilde-encode 格式（不預先展開）
        mirror = json.loads(paths["jsonl"].read_text(encoding="utf-8").strip())
        assert mirror["last_files"] == ["~/proj/foo.py", "~/proj/bar.py"]

    def test_agents_st_024_jsonl_mirror_stores_portable_path(self, paths: dict[str, Path]) -> None:
        """AGENTS-ST-024：JSONL 鏡像儲存的 working_dir 為 tilde-encode 格式（不展開）。"""
        write_handover(
            session_type=SessionType.admin,
            topic="t",
            summary="s",
            working_dir=str(Path.home() / "Workspace" / "test-proj"),
            db_path=paths["db"],
            jsonl_path=paths["jsonl"],
        )
        mirror = json.loads(paths["jsonl"].read_text(encoding="utf-8").strip())
        assert mirror["working_dir"] == "~/Workspace/test-proj"  # JSONL 存 portable 格式


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

    def test_agents_st_023_search_returns_expanded_working_dir(
        self, paths: dict[str, Path]
    ) -> None:
        """AGENTS-ST-023：search_handovers 回傳的 working_dir 已展開為絕對路徑。"""
        write_handover(
            session_type=SessionType.debug,
            topic="portable path search test",
            summary="s",
            working_dir=str(Path.home() / "Workspace" / "test-proj"),
            db_path=paths["db"],
            jsonl_path=paths["jsonl"],
        )
        rows = search_handovers(query="portable path search", db_path=paths["db"])
        assert rows[0]["working_dir"] == str(Path.home() / "Workspace" / "test-proj")


class TestReadRecent:
    def test_agents_dt_001_read_recent_excludes_tags(self, paths: dict[str, Path]) -> None:
        """AGENTS-DT-001：read_recent exclude_tags 排除含指定 tag 的記錄，且 substring 不誤排。"""
        write_handover(
            session_type=SessionType.discussion,
            topic="Retro: PR #1",
            summary="retro test",
            tags=["pr-retrospective"],
            db_path=paths["db"],
            jsonl_path=paths["jsonl"],
        )
        write_handover(
            session_type=SessionType.discussion,
            topic="false match test",
            summary="should not be excluded",
            tags=["not-pr-retrospective"],
            db_path=paths["db"],
            jsonl_path=paths["jsonl"],
        )
        write_handover(
            session_type=SessionType.sdd,
            topic="regular work",
            summary="normal handover",
            tags=["feature"],
            db_path=paths["db"],
            jsonl_path=paths["jsonl"],
        )

        rows = read_recent(last=10, exclude_tags=["pr-retrospective"], db_path=paths["db"])
        topics = [r["topic"] for r in rows]
        assert len(rows) == 2
        assert "Retro: PR #1" not in topics
        assert "false match test" in topics
        assert "regular work" in topics

    def test_agents_dt_002_exclude_multiple_tags(self, paths: dict[str, Path]) -> None:
        """AGENTS-DT-002：多個 exclude_tags 均 AND 排除（兩種 tag 都不出現在結果）。"""
        write_handover(
            session_type=SessionType.discussion,
            topic="retro record",
            summary="s",
            tags=["pr-retrospective"],
            db_path=paths["db"],
            jsonl_path=paths["jsonl"],
        )
        write_handover(
            session_type=SessionType.discussion,
            topic="learn record",
            summary="s",
            tags=["learn-only"],
            db_path=paths["db"],
            jsonl_path=paths["jsonl"],
        )
        write_handover(
            session_type=SessionType.sdd,
            topic="normal work",
            summary="s",
            tags=["feature"],
            db_path=paths["db"],
            jsonl_path=paths["jsonl"],
        )

        rows = read_recent(
            last=10,
            exclude_tags=["pr-retrospective", "learn-only"],
            db_path=paths["db"],
        )
        topics = [r["topic"] for r in rows]
        assert len(rows) == 1
        assert "normal work" in topics
        assert "retro record" not in topics
        assert "learn record" not in topics

    def test_agents_dt_003_exclude_tags_none_is_noop(self, paths: dict[str, Path]) -> None:
        """AGENTS-DT-003：exclude_tags=None 不過濾任何記錄。"""
        write_handover(
            session_type=SessionType.discussion,
            topic="retro record",
            summary="s",
            tags=["pr-retrospective"],
            db_path=paths["db"],
            jsonl_path=paths["jsonl"],
        )
        write_handover(
            session_type=SessionType.sdd,
            topic="normal work",
            summary="s",
            tags=["feature"],
            db_path=paths["db"],
            jsonl_path=paths["jsonl"],
        )

        rows = read_recent(last=10, exclude_tags=None, db_path=paths["db"])
        assert len(rows) == 2

    def test_agents_dt_004_exclude_tags_empty_list_is_noop(self, paths: dict[str, Path]) -> None:
        """AGENTS-DT-004：exclude_tags=[] 不過濾任何記錄。"""
        write_handover(
            session_type=SessionType.discussion,
            topic="retro record",
            summary="s",
            tags=["pr-retrospective"],
            db_path=paths["db"],
            jsonl_path=paths["jsonl"],
        )

        rows = read_recent(last=10, exclude_tags=[], db_path=paths["db"])
        assert len(rows) == 1

    def test_agents_dt_005_project_and_exclude_tags_combined(self, paths: dict[str, Path]) -> None:
        """AGENTS-DT-005：project + exclude_tags 交集過濾（proj-a retro 和 proj-b 都不出現）。"""
        write_handover(
            session_type=SessionType.sdd,
            topic="proj-a work",
            summary="s",
            tags=["feature"],
            project="proj-a",
            db_path=paths["db"],
            jsonl_path=paths["jsonl"],
        )
        write_handover(
            session_type=SessionType.discussion,
            topic="proj-a retro",
            summary="s",
            tags=["pr-retrospective"],
            project="proj-a",
            db_path=paths["db"],
            jsonl_path=paths["jsonl"],
        )
        write_handover(
            session_type=SessionType.sdd,
            topic="proj-b work",
            summary="s",
            tags=["feature"],
            project="proj-b",
            db_path=paths["db"],
            jsonl_path=paths["jsonl"],
        )

        rows = read_recent(
            last=10,
            project="proj-a",
            exclude_tags=["pr-retrospective"],
            db_path=paths["db"],
        )
        topics = [r["topic"] for r in rows]
        assert len(rows) == 1
        assert "proj-a work" in topics
        assert "proj-a retro" not in topics
        assert "proj-b work" not in topics


class TestExpandPaths:
    def test_agents_eg_031_expand_paths_does_not_mutate_input(self) -> None:
        """AGENTS-EG-031：_expand_paths 不修改傳入的原始 dict（docstring 承諾不變動原物件）。"""
        from tasks.mycelium.handover_service import _expand_paths

        original: dict[str, object] = {
            "working_dir": "~/proj",
            "last_files": ["~/proj/a.py"],
        }
        snapshot = dict(original)
        _expand_paths(original)
        assert original == snapshot

    def test_agents_eg_033_expand_paths_handles_null_fields(self) -> None:
        """AGENTS-EG-033：working_dir=None / last_files=None 時不拋 KeyError 或 TypeError。"""
        from tasks.mycelium.handover_service import _expand_paths

        result = _expand_paths({"working_dir": None, "last_files": None})
        assert result["working_dir"] is None
        assert result["last_files"] is None


class TestFromPortablePath:
    def test_agents_cv_019_tilde_username_raises(self) -> None:
        """AGENTS-CV-019：~username 形式應 raise ValueError，不可靜默回傳錯誤路徑。"""
        import pytest

        from tasks.mycelium.config import from_portable_path

        with pytest.raises(ValueError, match="~username"):
            from_portable_path("~otheruser/foo")


class TestAutoTokenUsage:
    """write_handover(auto_token_usage=True) 在三種 compute 狀態下都不能 raise。"""

    def test_agents_tok_st_003_computed_populates_fields(self, paths: dict[str, Path]) -> None:
        """AGENTS-TOK-ST-003：status=computed 時，8 個 token 欄位被填入。"""
        from tasks.mycelium.token_usage_service import TokenUsageReport

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
            record = write_handover(
                session_type=SessionType.discussion,
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

    def test_agents_tok_st_004_ambiguous_leaves_numeric_fields_none(
        self, paths: dict[str, Path]
    ) -> None:
        """AGENTS-TOK-ST-004：status=ambiguous 時只設 token_usage_source，數值仍是 None。"""
        from tasks.mycelium.token_usage_service import TokenUsageReport

        report = TokenUsageReport(status="ambiguous", warning="偵測到並行 session")
        with patch(
            "tasks.mycelium.token_usage_service.compute_token_usage_report",
            return_value=report,
        ):
            record = write_handover(
                session_type=SessionType.discussion,
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

    def test_agents_tok_eg_002_compute_raises_does_not_block_write(
        self, paths: dict[str, Path]
    ) -> None:
        """AGENTS-TOK-EG-002：token 用量計算本身 raise 例外時，write_handover 仍成功寫入。"""
        with patch(
            "tasks.mycelium.token_usage_service.compute_token_usage_report",
            side_effect=RuntimeError("boom"),
        ):
            record = write_handover(
                session_type=SessionType.discussion,
                topic="t",
                summary="s",
                auto_token_usage=True,
                db_path=paths["db"],
                jsonl_path=paths["jsonl"],
            )

        assert record.token_usage_source is None
        rows = read_recent(last=1, db_path=paths["db"])
        assert rows[0]["id"] == record.id

    def test_agents_tok_st_005_flag_off_skips_computation(self, paths: dict[str, Path]) -> None:
        """AGENTS-TOK-ST-005：auto_token_usage=False（預設）時完全不呼叫計算函式。"""
        with patch("tasks.mycelium.token_usage_service.compute_token_usage_report") as mock_compute:
            record = write_handover(
                session_type=SessionType.discussion,
                topic="t",
                summary="s",
                db_path=paths["db"],
                jsonl_path=paths["jsonl"],
            )

        mock_compute.assert_not_called()
        assert record.token_usage_source is None
