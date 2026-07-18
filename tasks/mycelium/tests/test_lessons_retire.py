"""LSN-DEL / LSN-RET: lessons delete（tombstone）與 retire（退場）機制測試。

涵蓋 DB 層（delete/retire/get_lesson/count_lessons、retired 排除）、
service 層（wrapper 驗證與 fail-loud）、CLI 層（含「無 --id 必須 fail」negative case）
與 distill harvest 排除 retired。對應 issue #242。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from click.testing import CliRunner

from tasks.mycelium.cli import cli
from tasks.mycelium.db import AgentsDB
from tasks.mycelium.distill_service import harvest
from tasks.mycelium.lessons_service import (
    delete_lesson,
    get_lesson,
    retire_lesson,
    search_lessons_typed,
    show_lessons_typed,
)
from tasks.mycelium.models import LessonRecord, LessonSource, LessonType

_NOW = datetime(2026, 7, 18, tzinfo=UTC)


def _make_lesson(**kwargs: object) -> LessonRecord:
    defaults: dict[str, object] = {
        "project": "yibi-stack",
        "type": LessonType.pitfall,
        "key": "sample-key",
        "insight": "A sufficiently long insight body for validation purposes.",
        "confidence": 8,
        "source": LessonSource.observed,
        "ts": _NOW.isoformat(),
    }
    return LessonRecord(**{**defaults, **kwargs})


def _seed(db_path: str, **kwargs: object) -> str:
    """寫入一筆 lesson，回傳其 id。"""
    db = AgentsDB(db_path=db_path)
    db.init_db()
    record = _make_lesson(**kwargs)
    db.insert_lesson(record)
    db.close()
    return record.id


def _db_file(tmp_path: Path) -> str:
    return str(tmp_path / "test.db")


# ─── Schema ────────────────────────────────────────────────────────────────


class TestSchema:
    def test_lsn_del_vl_001_tombstone_table_exists(self) -> None:
        """LSN-DEL-VL-001: lessons_deleted tombstone table 在 init_db 後存在"""
        db = AgentsDB(":memory:")
        db.init_db()
        cur = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='lessons_deleted'"
        )
        assert cur.fetchone() is not None
        db.close()

    def test_lsn_ret_vl_001_retired_columns_exist(self) -> None:
        """LSN-RET-VL-001: retired_at / retired_reason / superseded_by 欄位存在"""
        db = AgentsDB(":memory:")
        db.init_db()
        cols = {row[1] for row in db.conn.execute("PRAGMA table_info(lessons)")}
        assert {"retired_at", "retired_reason", "superseded_by"} <= cols
        db.close()


# ─── DB layer ──────────────────────────────────────────────────────────────


class TestDeleteDB:
    def test_lsn_del_dt_001_delete_removes_and_returns_row(self) -> None:
        """LSN-DEL-DT-001: delete_lesson 移除 row 並回傳被刪除內容"""
        db = AgentsDB(":memory:")
        db.init_db()
        record = _make_lesson(key="to-delete")
        db.insert_lesson(record)
        deleted = db.delete_lesson(record.id, _NOW)
        assert deleted is not None
        assert deleted["id"] == record.id
        assert db.get_lesson(record.id) is None
        db.close()

    def test_lsn_del_dt_002_delete_writes_tombstone(self) -> None:
        """LSN-DEL-DT-002: delete 前寫入 lessons_deleted tombstone（含 snapshot）"""
        import json

        db = AgentsDB(":memory:")
        db.init_db()
        record = _make_lesson(key="audit-me")
        db.insert_lesson(record)
        db.delete_lesson(record.id, _NOW)
        row = db.conn.execute(
            "SELECT id, deleted_at, key, snapshot FROM lessons_deleted WHERE id = ?",
            (record.id,),
        ).fetchone()
        assert row is not None
        assert row["key"] == "audit-me"
        assert row["deleted_at"] == _NOW.isoformat()
        snapshot = json.loads(row["snapshot"])
        assert snapshot["insight"] == record.insight
        db.close()

    def test_lsn_del_dt_003_delete_missing_returns_none_no_tombstone(self) -> None:
        """LSN-DEL-DT-003: 刪除不存在 id 回傳 None，且不寫 tombstone"""
        db = AgentsDB(":memory:")
        db.init_db()
        assert db.delete_lesson("no-such-id", _NOW) is None
        count = db.conn.execute("SELECT COUNT(*) AS c FROM lessons_deleted").fetchone()["c"]
        assert count == 0
        db.close()

    def test_lsn_del_dt_004_count_lessons_reflects_deletion(self) -> None:
        """LSN-DEL-DT-004: count_lessons 反映刪除後剩餘筆數"""
        db = AgentsDB(":memory:")
        db.init_db()
        r1 = _make_lesson(key="keep-a")
        r2 = _make_lesson(key="drop-b")
        db.insert_lesson(r1)
        db.insert_lesson(r2)
        assert db.count_lessons() == 2
        db.delete_lesson(r2.id, _NOW)
        assert db.count_lessons() == 1
        db.close()


class TestRetireDB:
    def test_lsn_ret_dt_001_retire_sets_fields(self) -> None:
        """LSN-RET-DT-001: retire_lesson 寫入 retired_at/reason/superseded_by 並保留內容"""
        db = AgentsDB(":memory:")
        db.init_db()
        record = _make_lesson(key="stale")
        db.insert_lesson(record)
        updated = db.retire_lesson(record.id, "被 PR #999 推翻", "new-key", _NOW)
        assert updated is not None
        assert updated["retired_at"] == _NOW.isoformat()
        assert updated["retired_reason"] == "被 PR #999 推翻"
        assert updated["superseded_by"] == "new-key"
        assert updated["insight"] == record.insight  # 內容保留
        db.close()

    def test_lsn_ret_dt_002_retire_missing_returns_none(self) -> None:
        """LSN-RET-DT-002: retire 不存在 id 回傳 None"""
        db = AgentsDB(":memory:")
        db.init_db()
        assert db.retire_lesson("no-such-id", "reason", None, _NOW) is None
        db.close()

    def test_lsn_ret_dt_003_query_excludes_retired_by_default(self) -> None:
        """LSN-RET-DT-003: query_lessons_typed 預設排除 retired，include_retired 才回傳"""
        db = AgentsDB(":memory:")
        db.init_db()
        live = _make_lesson(key="live-one")
        gone = _make_lesson(key="retired-one")
        db.insert_lesson(live)
        db.insert_lesson(gone)
        db.retire_lesson(gone.id, "outdated", None, _NOW)

        default_ids = {r["id"] for r in db.query_lessons_typed(project="yibi-stack")}
        assert live.id in default_ids
        assert gone.id not in default_ids

        all_ids = {
            r["id"] for r in db.query_lessons_typed(project="yibi-stack", include_retired=True)
        }
        assert gone.id in all_ids
        db.close()

    def test_lsn_ret_dt_004_search_excludes_retired_by_default(self) -> None:
        """LSN-RET-DT-004: search_lessons_typed 預設排除 retired"""
        db = AgentsDB(":memory:")
        db.init_db()
        gone = _make_lesson(key="retired-search", insight="unique-token needle to find here.")
        db.insert_lesson(gone)
        db.retire_lesson(gone.id, "outdated", None, _NOW)
        assert db.search_lessons_typed("needle", project="yibi-stack") == []
        found = db.search_lessons_typed("needle", project="yibi-stack", include_retired=True)
        assert {r["id"] for r in found} == {gone.id}
        db.close()


# ─── Service layer ───────────────────────────────────────────────────────────


class TestDeleteService:
    def test_lsn_del_st_001_delete_returns_remaining(self, tmp_path: Path) -> None:
        """LSN-DEL-ST-001: service delete_lesson 回傳 deleted row 與 remaining 筆數"""
        db_path = _db_file(tmp_path)
        lid = _seed(db_path, key="svc-del")
        _seed(db_path, key="svc-keep")
        result = delete_lesson(lid, db_path=db_path)
        assert result["deleted"]["id"] == lid
        assert result["remaining"] == 1

    def test_lsn_del_eg_001_delete_missing_raises_runtime(self, tmp_path: Path) -> None:
        """LSN-DEL-EG-001: 刪除不存在 id raise RuntimeError（fail loud，非靜默 no-op）"""
        db_path = _db_file(tmp_path)
        _seed(db_path, key="present")
        import pytest

        with pytest.raises(RuntimeError, match="找不到"):
            delete_lesson("no-such-id", db_path=db_path)

    def test_lsn_del_eg_002_delete_empty_id_raises_value(self, tmp_path: Path) -> None:
        """LSN-DEL-EG-002: 空白 id raise ValueError"""
        import pytest

        with pytest.raises(ValueError, match="不可為空"):
            delete_lesson("   ", db_path=_db_file(tmp_path))


class TestRetireService:
    def test_lsn_ret_st_001_retire_sets_fields(self, tmp_path: Path) -> None:
        """LSN-RET-ST-001: service retire_lesson 回傳更新後 row"""
        db_path = _db_file(tmp_path)
        lid = _seed(db_path, key="svc-retire")
        updated = retire_lesson(lid, "被推翻", "replacement", db_path=db_path)
        assert updated["retired_reason"] == "被推翻"
        assert updated["superseded_by"] == "replacement"
        # 退場後 get_lesson 仍取得（內容保留）
        assert get_lesson(lid, db_path=db_path) is not None

    def test_lsn_ret_eg_001_empty_reason_raises(self, tmp_path: Path) -> None:
        """LSN-RET-EG-001: retire 無 reason（空白）raise ValueError"""
        db_path = _db_file(tmp_path)
        lid = _seed(db_path, key="need-reason")
        import pytest

        with pytest.raises(ValueError, match="reason"):
            retire_lesson(lid, "   ", None, db_path=db_path)

    def test_lsn_ret_eg_002_retire_missing_raises_runtime(self, tmp_path: Path) -> None:
        """LSN-RET-EG-002: retire 不存在 id raise RuntimeError"""
        import pytest

        with pytest.raises(RuntimeError, match="找不到"):
            retire_lesson("no-such-id", "reason", None, db_path=_db_file(tmp_path))

    def test_lsn_ret_st_002_show_search_exclude_retired(self, tmp_path: Path) -> None:
        """LSN-RET-ST-002: service show/search 預設排除 retired，include_retired 才回傳"""
        db_path = _db_file(tmp_path)
        lid = _seed(db_path, key="svc-hidden", insight="findme service-level token here today.")
        retire_lesson(lid, "outdated", None, db_path=db_path)

        shown = show_lessons_typed(project="yibi-stack", include_legacy=False, db_path=db_path)
        assert all(r["id"] != lid for r in shown)
        shown_all = show_lessons_typed(
            project="yibi-stack", include_legacy=False, db_path=db_path, include_retired=True
        )
        assert any(r["id"] == lid for r in shown_all)

        searched = search_lessons_typed(
            "findme", project="yibi-stack", include_legacy=False, db_path=db_path
        )
        assert searched == []
        searched_all = search_lessons_typed(
            "findme",
            project="yibi-stack",
            include_legacy=False,
            db_path=db_path,
            include_retired=True,
        )
        assert any(r["id"] == lid for r in searched_all)


# ─── Distill exclusion ───────────────────────────────────────────────────────


class TestDistillExcludesRetired:
    def test_lsn_ret_st_003_harvest_excludes_retired(self, tmp_path: Path) -> None:
        """LSN-RET-ST-003: distill harvest 不聚合 retired 教訓"""
        db_path = _db_file(tmp_path)
        live = _seed(db_path, key="harvest-live")
        gone = _seed(db_path, key="harvest-gone")
        retire_lesson(gone, "outdated", None, db_path=db_path)
        result = harvest(since="3650d", db_path=db_path, now=datetime(2026, 7, 19, tzinfo=UTC))
        ids = {r["id"] for r in result.lessons}
        assert live in ids
        assert gone not in ids


# ─── CLI layer ───────────────────────────────────────────────────────────────


class TestDeleteCLI:
    def _env(self, db_path: str) -> dict[str, str]:
        import os

        return {**os.environ, "MYCELIUM_DB_OVERRIDE": db_path}

    def test_lsn_del_cv_001_delete_by_id(self, tmp_path: Path) -> None:
        """LSN-DEL-CV-001: lessons delete --id 移除單筆並印出剩餘筆數"""
        db_path = _db_file(tmp_path)
        lid = _seed(db_path, key="cli-del")
        runner = CliRunner()
        result = runner.invoke(cli, ["lessons", "delete", "--id", lid], env=self._env(db_path))
        assert result.exit_code == 0, result.output
        assert "剩餘 lessons 筆數（不含 retired" in result.output
        assert "：0" in result.output

    def test_lsn_del_cv_002_missing_id_fails(self, tmp_path: Path) -> None:
        """LSN-DEL-CV-002 (negative): 無 --id 必須 fail（click required，非零 exit）"""
        runner = CliRunner()
        result = runner.invoke(cli, ["lessons", "delete"], env=self._env(_db_file(tmp_path)))
        assert result.exit_code != 0
        assert "--id" in result.output

    def test_lsn_del_cv_003_missing_id_value_exits_1(self, tmp_path: Path) -> None:
        """LSN-DEL-CV-003: --id 指向不存在教訓，exit 1 並提示找不到"""
        runner = CliRunner()
        result = runner.invoke(
            cli, ["lessons", "delete", "--id", "no-such"], env=self._env(_db_file(tmp_path))
        )
        assert result.exit_code == 1
        assert "找不到" in result.output

    def test_lsn_del_cv_004_dry_run_does_not_delete(self, tmp_path: Path) -> None:
        """LSN-DEL-CV-004: --dry-run 只顯示，不實際刪除"""
        db_path = _db_file(tmp_path)
        lid = _seed(db_path, key="cli-dry")
        runner = CliRunner()
        result = runner.invoke(
            cli, ["lessons", "delete", "--id", lid, "--dry-run"], env=self._env(db_path)
        )
        assert result.exit_code == 0
        assert "dry-run" in result.output
        # 仍存在
        assert get_lesson(lid, db_path=db_path) is not None


class TestRetireCLI:
    def _env(self, db_path: str) -> dict[str, str]:
        import os

        return {**os.environ, "MYCELIUM_DB_OVERRIDE": db_path}

    def test_lsn_ret_cv_001_retire_by_id(self, tmp_path: Path) -> None:
        """LSN-RET-CV-001: lessons retire --id --reason 標記退場"""
        db_path = _db_file(tmp_path)
        lid = _seed(db_path, key="cli-retire")
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "lessons",
                "retire",
                "--id",
                lid,
                "--reason",
                "被 PR #1 推翻",
                "--superseded-by",
                "nk",
            ],
            env=self._env(db_path),
        )
        assert result.exit_code == 0, result.output
        assert "已退場" in result.output
        row = get_lesson(lid, db_path=db_path)
        assert row is not None
        assert row["retired_reason"] == "被 PR #1 推翻"
        assert row["superseded_by"] == "nk"

    def test_lsn_ret_cv_002_missing_id_fails(self, tmp_path: Path) -> None:
        """LSN-RET-CV-002 (negative): 無 --id 必須 fail"""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["lessons", "retire", "--reason", "x"],
            env=self._env(_db_file(tmp_path)),
        )
        assert result.exit_code != 0
        assert "--id" in result.output

    def test_lsn_ret_cv_003_missing_reason_fails(self, tmp_path: Path) -> None:
        """LSN-RET-CV-003 (negative): 無 --reason 必須 fail"""
        db_path = _db_file(tmp_path)
        lid = _seed(db_path, key="cli-noreason")
        runner = CliRunner()
        result = runner.invoke(cli, ["lessons", "retire", "--id", lid], env=self._env(db_path))
        assert result.exit_code != 0
        assert "--reason" in result.output


# ─── Re-retire guard (audit-trail preservation) ──────────────────────────────


class TestReRetireGuard:
    def test_lsn_ret_dt_005_db_reretire_returns_none(self) -> None:
        """LSN-RET-DT-005: db.retire_lesson 對已 retire 的 lesson 回傳 None（不覆寫）"""
        db = AgentsDB(":memory:")
        db.init_db()
        record = _make_lesson(key="reretire-db")
        db.insert_lesson(record)
        first = db.retire_lesson(record.id, "first reason", "orig-key", _NOW)
        assert first is not None
        second = db.retire_lesson(record.id, "second reason", None, _NOW)
        assert second is None  # WHERE retired_at IS NULL -> 0 rows
        # 原始退場記錄未被覆寫
        row = db.get_lesson(record.id)
        assert row is not None
        assert row["retired_reason"] == "first reason"
        assert row["superseded_by"] == "orig-key"
        db.close()

    def test_lsn_ret_eg_003_service_reretire_raises(self, tmp_path: Path) -> None:
        """LSN-RET-EG-003: service retire_lesson 對已 retire 的 lesson fail loud，並保留原記錄"""
        db_path = _db_file(tmp_path)
        lid = _seed(db_path, key="reretire-svc")
        retire_lesson(lid, "被 PR #1 推翻", "orig-key", db_path=db_path)
        import pytest

        with pytest.raises(RuntimeError, match="已於"):
            retire_lesson(lid, "誤打的第二次", None, db_path=db_path)
        # 原始退場理由與取代者未被覆寫
        row = get_lesson(lid, db_path=db_path)
        assert row is not None
        assert row["retired_reason"] == "被 PR #1 推翻"
        assert row["superseded_by"] == "orig-key"

    def test_lsn_ret_cv_004_cli_reretire_exits_1(self, tmp_path: Path) -> None:
        """LSN-RET-CV-004: CLI 重複 retire exit 1，訊息帶原始退場資訊"""
        db_path = _db_file(tmp_path)
        lid = _seed(db_path, key="reretire-cli")
        retire_lesson(lid, "first", "ok", db_path=db_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["lessons", "retire", "--id", lid, "--reason", "second"],
            env={**__import__("os").environ, "MYCELIUM_DB_OVERRIDE": db_path},
        )
        assert result.exit_code == 1
        assert "已於" in result.output


# ─── Delete concurrency safety ───────────────────────────────────────────────


class TestDeleteConcurrencySafety:
    def test_lsn_del_dt_005_race_no_orphan_tombstone(self, monkeypatch) -> None:
        """LSN-DEL-DT-005: get_lesson 回傳 row 但 DELETE 命中 0 rows（併發刪除）→
        不寫 tombstone、回傳 None（避免孤兒 tombstone）"""
        db = AgentsDB(":memory:")
        db.init_db()
        fake = {"id": "ghost", "project": "p", "key": "k", "type": "pitfall", "insight": "x"}
        # 模擬 TOCTOU：get_lesson 回傳一個實際不在 table 的 row
        monkeypatch.setattr(db, "get_lesson", lambda _id: fake)
        result = db.delete_lesson("ghost", _NOW)
        assert result is None
        tomb = db.conn.execute("SELECT COUNT(*) AS c FROM lessons_deleted").fetchone()["c"]
        assert tomb == 0
        db.close()

    def test_lsn_del_dt_006_atomic_rollback_on_tombstone_error(self, monkeypatch) -> None:
        """LSN-DEL-DT-006: tombstone INSERT 失敗時整個 transaction rollback——
        DELETE 被還原（row 保留）、無 tombstone"""
        import pytest

        db = AgentsDB(":memory:")
        db.init_db()
        record = _make_lesson(key="atomic")
        db.insert_lesson(record)

        def _boom(*_a: object, **_k: object) -> str:
            raise ValueError("tombstone serialize boom")

        # 讓 tombstone INSERT 前的 json.dumps 拋錯（DELETE 已執行、tombstone 尚未寫入）
        monkeypatch.setattr("tasks.mycelium.db.json.dumps", _boom)
        with pytest.raises(ValueError):
            db.delete_lesson(record.id, _NOW)
        monkeypatch.undo()
        # DELETE 被 rollback：row 仍在，且無 tombstone
        assert db.get_lesson(record.id) is not None
        tomb = db.conn.execute("SELECT COUNT(*) AS c FROM lessons_deleted").fetchone()["c"]
        assert tomb == 0
        db.close()


# ─── Remaining count excludes retired ────────────────────────────────────────


class TestRemainingCountExcludesRetired:
    def test_lsn_del_st_002_remaining_counts_only_live(self, tmp_path: Path) -> None:
        """LSN-DEL-ST-002: delete 回報的 remaining 只計非 retired（與 show 一致）"""
        db_path = _db_file(tmp_path)
        live = _seed(db_path, key="live-a")
        _seed(db_path, key="live-b")
        retired = _seed(db_path, key="retired-c")
        retire_lesson(retired, "outdated", None, db_path=db_path)
        # 刪掉 live-a：剩 live-b（live）+ retired-c（retired）= 1 live remaining
        result = delete_lesson(live, db_path=db_path)
        assert result["remaining"] == 1  # 不含 retired-c

    def test_lsn_del_dt_007_count_lessons_include_retired_flag(self) -> None:
        """LSN-DEL-DT-007: count_lessons(include_retired=) 分別計入／排除 retired"""
        db = AgentsDB(":memory:")
        db.init_db()
        live = _make_lesson(key="cnt-live")
        gone = _make_lesson(key="cnt-gone")
        db.insert_lesson(live)
        db.insert_lesson(gone)
        db.retire_lesson(gone.id, "outdated", None, _NOW)
        assert db.count_lessons(include_retired=True) == 2
        assert db.count_lessons(include_retired=False) == 1
        db.close()


# ─── Dry-run missing id ──────────────────────────────────────────────────────


class TestDryRunMissingId:
    def test_lsn_del_cv_005_dry_run_missing_id_exits_1(self, tmp_path: Path) -> None:
        """LSN-DEL-CV-005: delete --dry-run 對不存在 id exit 1 並提示找不到"""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["lessons", "delete", "--id", "no-such", "--dry-run"],
            env={**__import__("os").environ, "MYCELIUM_DB_OVERRIDE": _db_file(tmp_path)},
        )
        assert result.exit_code == 1
        assert "找不到" in result.output


# ─── CLI --include-retired rendering ─────────────────────────────────────────


class TestIncludeRetiredCLI:
    def _env(self, db_path: str) -> dict[str, str]:
        import os

        return {**os.environ, "MYCELIUM_DB_OVERRIDE": db_path}

    def test_lsn_show_cv_001_default_excludes_retired(self, tmp_path: Path) -> None:
        """LSN-SHOW-CV-001: show 預設不顯示 retired（typed 路徑）"""
        db_path = _db_file(tmp_path)
        lid = _seed(db_path, key="hidden-show", insight="findme show-level unique token here.")
        retire_lesson(lid, "outdated", None, db_path=db_path)
        runner = CliRunner()
        # --no-include-legacy 走 typed 路徑；--json 便於精確斷言
        result = runner.invoke(
            cli,
            ["lessons", "show", "--no-include-legacy", "--json"],
            env=self._env(db_path),
        )
        assert result.exit_code == 0, result.output
        assert "hidden-show" not in result.output

    def test_lsn_show_cv_002_include_retired_shows_tag_and_superseded(self, tmp_path: Path) -> None:
        """LSN-SHOW-CV-002: show --include-retired 顯示 [RETIRED]、reason、superseded_by"""
        db_path = _db_file(tmp_path)
        lid = _seed(db_path, key="shown-retired")
        retire_lesson(lid, "被 PR #7 推翻", "new-canonical", db_path=db_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["lessons", "show", "--no-include-legacy", "--include-retired"],
            env=self._env(db_path),
        )
        assert result.exit_code == 0, result.output
        assert "[RETIRED]" in result.output
        assert "被 PR #7 推翻" in result.output
        assert "superseded_by=new-canonical" in result.output

    def test_lsn_search_cv_001_include_retired(self, tmp_path: Path) -> None:
        """LSN-SEARCH-CV-001: search 預設排除 retired，--include-retired 才顯示並標 [RETIRED]"""
        db_path = _db_file(tmp_path)
        lid = _seed(db_path, key="srch-retired", insight="needle-token in a retired lesson here.")
        retire_lesson(lid, "被推翻", "repl", db_path=db_path)
        runner = CliRunner()
        default = runner.invoke(
            cli,
            ["lessons", "search", "needle-token", "--no-include-legacy"],
            env=self._env(db_path),
        )
        assert default.exit_code == 0
        assert "srch-retired" not in default.output
        with_flag = runner.invoke(
            cli,
            ["lessons", "search", "needle-token", "--no-include-legacy", "--include-retired"],
            env=self._env(db_path),
        )
        assert with_flag.exit_code == 0, with_flag.output
        assert "[RETIRED]" in with_flag.output


# ─── tier_service excludes retired ───────────────────────────────────────────


class TestTierServiceExcludesRetired:
    def test_lsn_ret_st_004_tier_promotion_skips_retired(self, tmp_path: Path) -> None:
        """LSN-RET-ST-004: tier 升降級掃描（_fetch_non_archival）排除 retired"""
        from tasks.mycelium.tier_service import _fetch_non_archival

        db_path = _db_file(tmp_path)
        live = _seed(db_path, key="tier-live")
        gone = _seed(db_path, key="tier-gone")
        db = AgentsDB(db_path=db_path)
        db.init_db()
        db.retire_lesson(gone, "outdated", None, _NOW)
        rows = _fetch_non_archival(db)
        ids = {r["id"] for r in rows}
        db.close()
        assert live in ids
        assert gone not in ids
