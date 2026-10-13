"""LROWS：mycelium lessons rows 唯讀 canonical 讀回測試。

對應 change fix-hindsight-canonical-readback（capability lesson-canonical-readback）。
核心情境：WAL 模式且 -shm／-wal 已不存在的 DB，mode=ro 開不了，rows 子指令仍要讀得到，
而且不得建立 DB、建表或寫入任何列。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from tasks.mycelium.cli import cli
from tasks.mycelium.db import AgentsDB
from tasks.mycelium.lessons_service import show_lessons_typed
from tasks.mycelium.models import LessonRecord, LessonSource, LessonType

_PROJECT = "yibi-stack"
_TS = datetime(2026, 7, 18, tzinfo=UTC)
_PINNED_NOW = datetime(2026, 4, 15, tzinfo=UTC)


class _FixedNowDatetime(datetime):
    """now() 固定回傳 _PINNED_NOW 的 datetime，用來釘住 _apply_decay 的衰減時鐘。"""

    @classmethod
    def now(cls, tz: Any = None) -> _FixedNowDatetime:
        pinned = cls.fromtimestamp(_PINNED_NOW.timestamp(), tz=UTC)
        return pinned if tz is None else pinned.astimezone(tz)


def _make_lesson(**kwargs: object) -> LessonRecord:
    defaults: dict[str, object] = {
        "project": _PROJECT,
        "type": LessonType.pitfall,
        "key": "sample-key",
        "insight": "A sufficiently long insight body for validation purposes.",
        "confidence": 8,
        "source": LessonSource.observed,
        "ts": _TS.isoformat(),
    }
    return LessonRecord(**{**defaults, **kwargs})


def _seed(db_path: Path, *records: LessonRecord) -> None:
    db = AgentsDB(db_path=str(db_path))
    db.init_db()
    for record in records:
        db.insert_lesson(record)
    db.close()


def _retire(db_path: Path, lesson_id: str, superseded_by: str | None) -> None:
    db = AgentsDB(db_path=str(db_path))
    db.init_db()
    assert db.retire_lesson(lesson_id, "replaced", superseded_by, _TS) is not None
    db.close()


def _strip_wal_sidecars(db_path: Path) -> None:
    """checkpoint 後移除 -shm／-wal，重現正式 handover.db 的檔案狀態。"""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    for suffix in ("-shm", "-wal"):
        sidecar = db_path.with_name(db_path.name + suffix)
        if sidecar.exists():
            sidecar.unlink()
    assert db_path.read_bytes()[18:20] == b"\x02\x02", "fixture 必須是 WAL 模式"
    assert not db_path.with_name(db_path.name + "-shm").exists()


def _lesson_count(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return int(conn.execute("SELECT count(*) FROM lessons").fetchone()[0])
    finally:
        conn.close()


def _run(monkeypatch: pytest.MonkeyPatch, db_path: Path, *args: str) -> Result:
    monkeypatch.setenv("MYCELIUM_DB_OVERRIDE", str(db_path))
    return CliRunner().invoke(cli, ["lessons", "rows", *args])


def _ok_json(result: Result) -> dict[str, Any]:
    assert result.exit_code == 0, (result.exit_code, result.stdout, result.stderr)
    data: dict[str, Any] = json.loads(result.stdout)
    return data


@pytest.fixture
def wal_db(tmp_path: Path) -> Path:
    """WAL 模式、無 -shm／-wal 的 DB，含一筆 sample-key。"""
    db_path = tmp_path / "handover.db"
    _seed(db_path, _make_lesson(key="sample-key"))
    _strip_wal_sidecars(db_path)
    return db_path


class TestWalWithoutShm:
    def test_lrows_eg_001_mode_ro_fails_on_fixture(self, wal_db: Path) -> None:
        """LROWS-EG-001: 對照組：在會重現的 SQLite 上，fixture 的 mode=ro 開不了

        mode=ro 的失敗取決於 SQLite 版本：3.51.0 失敗、3.47.1 會自行建立 -shm 而成功。
        不重現的版本上明確 skip 並附版本號，不得靜默通過。
        """
        try:
            conn = sqlite3.connect(wal_db.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                conn.execute("SELECT count(*) FROM lessons").fetchone()
            finally:
                conn.close()
        except sqlite3.OperationalError as e:
            assert "unable to open database file" in str(e)
            return
        pytest.skip(f"SQLite {sqlite3.sqlite_version} 不重現 WAL 無 -shm 時 mode=ro 開啟失敗")

    def test_lrows_eg_002_rows_reads_wal_without_shm(
        self, wal_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LROWS-EG-002: WAL 無 -shm 時 rows 子指令仍 exit 0 並回傳列"""
        data = _ok_json(_run(monkeypatch, wal_db, "--project", _PROJECT, "--key", "sample-key"))
        assert [r["key"] for r in data["rows"]] == ["sample-key"]


class TestCompleteCanonicalRowListing:
    def test_lrows_dt_001_duplicate_key_rows_all_returned(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LROWS-DT-001: 同 key 一列 active、一列 retired 帶 superseded_by，兩列都回傳"""
        db_path = tmp_path / "dup.db"
        old = _make_lesson(key="dup-key", ts="2026-07-01T00:00:00+00:00")
        new = _make_lesson(key="dup-key", ts="2026-07-10T00:00:00+00:00")
        _seed(db_path, old, new)
        _retire(db_path, old.id, superseded_by=new.id)

        data = _ok_json(_run(monkeypatch, db_path, "--project", _PROJECT, "--key", "dup-key"))
        by_id = {r["id"]: r for r in data["rows"]}
        assert set(by_id) == {old.id, new.id}
        assert by_id[old.id]["retired_at"] is not None
        assert by_id[old.id]["superseded_by"] == new.id
        assert by_id[new.id]["retired_at"] is None

    def test_lrows_dt_002_parked_and_retired_included(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LROWS-DT-002: parked 與 retired 列都回傳，tags 是 JSON 陣列"""
        db_path = tmp_path / "inactive.db"
        parked = _make_lesson(key="parked-key", confidence=3, tags=["parked"])
        retired = _make_lesson(key="retired-key")
        _seed(db_path, parked, retired)
        _retire(db_path, retired.id, superseded_by=None)

        data = _ok_json(
            _run(
                monkeypatch,
                db_path,
                "--project",
                _PROJECT,
                "--key",
                "parked-key",
                "--key",
                "retired-key",
            )
        )
        by_key = {r["key"]: r for r in data["rows"]}
        assert by_key["parked-key"]["tags"] == ["parked"]
        assert isinstance(by_key["retired-key"]["tags"], list)
        assert by_key["retired-key"]["retired_at"] is not None

    def test_lrows_dt_003_missing_identifiers_reported(
        self, wal_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LROWS-DT-003: 未命中的 key／id 列入 missing，命中的照常回傳，exit 0"""
        data = _ok_json(
            _run(
                monkeypatch,
                wal_db,
                "--project",
                _PROJECT,
                "--key",
                "sample-key",
                "--key",
                "absent-key",
                "--id",
                "absent-id",
            )
        )
        assert [r["key"] for r in data["rows"]] == ["sample-key"]
        assert data["missing_keys"] == ["absent-key"]
        assert data["missing_ids"] == ["absent-id"]

    def test_lrows_dt_004_other_project_id_excluded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LROWS-DT-004: 只存在於別的 project 的 id 不回傳並列入 missing_ids"""
        db_path = tmp_path / "xproj.db"
        foreign = _make_lesson(project="other-project", key="foreign-key")
        _seed(db_path, foreign)

        data = _ok_json(_run(monkeypatch, db_path, "--project", _PROJECT, "--id", foreign.id))
        assert data["rows"] == []
        assert data["missing_ids"] == [foreign.id]

    def test_lrows_cv_001_ordering_and_requested_normalized(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LROWS-CV-001: rows 依 key、ts、id 排序；requested 去重排序；輸出結構完整"""
        db_path = tmp_path / "order.db"
        b_late = _make_lesson(key="b-key", ts="2026-07-05T00:00:00+00:00")
        b_early = _make_lesson(key="b-key", ts="2026-07-01T00:00:00+00:00")
        a_only = _make_lesson(key="a-key", ts="2026-07-09T00:00:00+00:00")
        _seed(db_path, b_late, b_early, a_only)

        data = _ok_json(
            _run(
                monkeypatch,
                db_path,
                "--project",
                _PROJECT,
                "--key",
                "b-key",
                "--key",
                "a-key",
                "--key",
                "b-key",
            )
        )
        assert data["schema_version"] == 1
        assert data["project"] == _PROJECT
        assert data["requested"] == {"keys": ["a-key", "b-key"], "ids": []}
        assert [r["id"] for r in data["rows"]] == [a_only.id, b_early.id, b_late.id]

    def test_lrows_cv_002_same_key_same_ts_ordered_by_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LROWS-CV-002: 同 key 同 ts 的多列以 id 遞增排序"""
        db_path = tmp_path / "tie.db"
        same_ts = "2026-07-03T00:00:00+00:00"
        records = [_make_lesson(key="tie-key", ts=same_ts) for _ in range(3)]
        _seed(db_path, *records)

        data = _ok_json(_run(monkeypatch, db_path, "--project", _PROJECT, "--key", "tie-key"))
        ids = [r["id"] for r in data["rows"]]
        assert ids == sorted(r.id for r in records)

    def test_lrows_dt_006_id_only_lookup_returns_row(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LROWS-DT-006: 只給 --id 時回傳同 project 的該列，missing_ids 為空"""
        db_path = tmp_path / "byid.db"
        target = _make_lesson(key="target-key")
        other = _make_lesson(key="other-key")
        _seed(db_path, target, other)

        data = _ok_json(_run(monkeypatch, db_path, "--project", _PROJECT, "--id", target.id))
        assert [r["id"] for r in data["rows"]] == [target.id]
        assert data["missing_ids"] == []
        assert data["missing_keys"] == []

    def test_lrows_dt_007_key_and_id_hitting_same_row_returned_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LROWS-DT-007: --key 與 --id 命中同一列時只回傳一次，兩者都不列入 missing"""
        db_path = tmp_path / "mixed.db"
        target = _make_lesson(key="mixed-key")
        _seed(db_path, target)

        data = _ok_json(
            _run(
                monkeypatch,
                db_path,
                "--project",
                _PROJECT,
                "--key",
                "mixed-key",
                "--id",
                target.id,
            )
        )
        assert [r["id"] for r in data["rows"]] == [target.id]
        assert data["missing_keys"] == []
        assert data["missing_ids"] == []


class TestReadOnlyOpenWithoutCreatingTheDatabase:
    def test_lrows_eg_003_missing_database_not_created(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LROWS-EG-003: DB 不存在時 exit 3、stdout 空、[FAIL] 在 stderr，且不建檔"""
        db_path = tmp_path / "nope" / "handover.db"
        result = _run(monkeypatch, db_path, "--project", _PROJECT, "--key", "sample-key")
        assert result.exit_code == 3
        assert result.stdout == ""
        assert result.stderr.startswith("[FAIL]")
        assert not db_path.exists()

    def test_lrows_eg_004_connection_rejects_writes(self, wal_db: Path) -> None:
        """LROWS-EG-004: 唯讀開啟的連線拒絕 INSERT，列數不變"""
        from tasks.mycelium.db import open_lessons_readonly

        before = _lesson_count(wal_db)
        conn = open_lessons_readonly(wal_db)
        try:
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                conn.execute(
                    "INSERT INTO lessons (id, ts, project, type, key, insight, confidence, source) "
                    "VALUES ('x', 't', 'p', 'pitfall', 'k', 'insight text here', 5, 'observed')"
                )
        finally:
            conn.close()
        assert _lesson_count(wal_db) == before

    def test_lrows_eg_005_missing_lessons_table(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LROWS-EG-005: DB 存在但沒有 lessons table 時 exit 3，且不建表"""
        db_path = tmp_path / "empty.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE other (x INTEGER)")
        conn.commit()
        conn.close()

        result = _run(monkeypatch, db_path, "--project", _PROJECT, "--key", "sample-key")
        assert result.exit_code == 3
        assert result.stdout == ""
        assert result.stderr.startswith("[FAIL]")
        conn = sqlite3.connect(db_path)
        try:
            tables = {
                r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        finally:
            conn.close()
        assert tables == {"other"}

    def test_lrows_eg_007_missing_file_in_existing_dir_not_created(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LROWS-EG-007: 父目錄存在但 DB 檔不存在時 exit 3，且不建立空檔"""
        db_path = tmp_path / "handover.db"
        assert tmp_path.is_dir()
        result = _run(monkeypatch, db_path, "--project", _PROJECT, "--key", "sample-key")
        assert result.exit_code == 3
        assert result.stdout == ""
        assert result.stderr.startswith("[FAIL]")
        assert not db_path.exists()

    def test_lrows_eg_008_not_a_database_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LROWS-EG-008: MYCELIUM_DB_OVERRIDE 指向非 SQLite 檔時 exit 3、stdout 空、[FAIL]"""
        db_path = tmp_path / "garbage.db"
        db_path.write_bytes(b"not a db")
        result = _run(monkeypatch, db_path, "--project", _PROJECT, "--key", "sample-key")
        assert result.exit_code == 3
        assert result.stdout == ""
        assert result.stderr.startswith("[FAIL]")

    def test_lrows_eg_009_query_error_on_missing_ts_column(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LROWS-EG-009: lessons table 缺 ts 欄位使 ORDER BY 查詢失敗時 exit 3、[FAIL]"""
        db_path = tmp_path / "nots.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE lessons (id TEXT, project TEXT, key TEXT)")
        conn.execute("INSERT INTO lessons VALUES ('x1', ?, 'sample-key')", (_PROJECT,))
        conn.commit()
        conn.close()

        result = _run(monkeypatch, db_path, "--project", _PROJECT, "--key", "sample-key")
        assert result.exit_code == 3
        assert result.stdout == ""
        assert result.stderr.startswith("[FAIL]")

    def test_lrows_eg_010_missing_confidence_column(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LROWS-EG-010: lessons table 缺 confidence 欄位時 exit 3、[FAIL]，不吐 traceback"""
        db_path = tmp_path / "noconf.db"
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE lessons (id TEXT, ts TEXT, project TEXT, type TEXT, key TEXT, "
            "insight TEXT, source TEXT, tags TEXT, files TEXT)"
        )
        conn.execute(
            "INSERT INTO lessons VALUES ('x1', ?, ?, 'pitfall', 'sample-key', "
            "'insight text here', 'observed', '[]', '[]')",
            (_TS.isoformat(), _PROJECT),
        )
        conn.commit()
        conn.close()

        result = _run(monkeypatch, db_path, "--project", _PROJECT, "--key", "sample-key")
        assert result.exit_code == 3
        assert result.stdout == ""
        assert result.stderr.startswith("[FAIL]")

    @pytest.mark.parametrize(
        ("column", "raw"),
        [
            pytest.param("tags", '["park', id="tags-truncated-json"),
            pytest.param("tags", "{}", id="tags-json-object"),
            pytest.param("tags", "null", id="tags-json-null"),
            pytest.param("files", '["a.py', id="files-truncated-json"),
            pytest.param("files", '{"a": 1}', id="files-json-object"),
            pytest.param("files", "null", id="files-json-null"),
        ],
    )
    def test_lrows_eg_011_corrupted_tags_json_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, column: str, raw: str
    ) -> None:
        """LROWS-EG-011: tags／files 不是合法 JSON 陣列時 exit 3，不得靜默重設為 []

        涵蓋截斷 JSON、JSON 物件、JSON null。物件與 null 能通過 json.loads，
        只有「不是陣列」的檢查擋得住，所以兩類都要測。
        """
        db_path = tmp_path / "badtags.db"
        parked = _make_lesson(key="parked-key", confidence=3, tags=["parked"])
        _seed(db_path, parked)
        conn = sqlite3.connect(db_path)
        # column 只來自上方固定的參數清單，不是外部輸入
        sql = f"UPDATE lessons SET {column} = ? WHERE id = ?"  # nosec B608
        conn.execute(sql, (raw, parked.id))
        conn.commit()
        conn.close()

        result = _run(monkeypatch, db_path, "--project", _PROJECT, "--key", "parked-key")
        assert result.exit_code == 3
        assert result.stdout == ""
        assert result.stderr.startswith("[FAIL]")


class TestExitStatusDistinguishesFailureFromAnEmptyResult:
    @pytest.mark.parametrize(
        "args",
        [
            pytest.param(["--project", _PROJECT], id="no-key-no-id"),
            pytest.param(
                ["--project", _PROJECT, *[a for i in range(201) for a in ("--key", f"k{i}")]],
                id="201-identifiers",
            ),
            pytest.param(["--project", _PROJECT, "--key", "has space"], id="key-with-space"),
            pytest.param(["--project", "", "--key", "sample-key"], id="empty-project"),
            pytest.param(["--project", "   ", "--key", "sample-key"], id="whitespace-project"),
            pytest.param(
                ["--project", f" {_PROJECT} ", "--key", "sample-key"],
                id="surrounding-whitespace-project",
            ),
            pytest.param(["--project", _PROJECT, "--id", ""], id="empty-id"),
        ],
    )
    def test_lrows_vl_001_invalid_arguments_exit_2(
        self, wal_db: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]
    ) -> None:
        """LROWS-VL-001: 參數不合法一律 exit 2"""
        assert _run(monkeypatch, wal_db, *args).exit_code == 2

    def test_lrows_vl_002_two_hundred_identifiers_accepted(
        self, wal_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LROWS-VL-002: 邊界值：合計 200 個識別碼可接受"""
        args = [a for i in range(200) for a in ("--key", f"k{i}")]
        data = _ok_json(_run(monkeypatch, wal_db, "--project", _PROJECT, *args))
        assert len(data["missing_keys"]) == 200

    def test_lrows_dt_005_zero_rows_is_success(
        self, wal_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LROWS-DT-005: 全部未命中時 exit 0、rows 為空陣列"""
        data = _ok_json(
            _run(monkeypatch, wal_db, "--project", _PROJECT, "--key", "nothing", "--id", "none")
        )
        assert data["rows"] == []
        assert data["missing_keys"] == ["nothing"]
        assert data["missing_ids"] == ["none"]


class TestEffectiveConfidenceParity:
    def test_lrows_st_001_matches_show_lessons_typed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LROWS-ST-001: effective_confidence 與 show_lessons_typed 對同一列的值相同

        衰減時鐘釘在固定時點（ts 後 104 天，observed 衰減 3），兩邊都用同一個 now，
        期望值不隨實際日期漂移，也不會因兩次呼叫跨過 30 天邊界而偶發失敗。
        """
        monkeypatch.setattr("tasks.mycelium.lessons_service.datetime", _FixedNowDatetime)
        db_path = tmp_path / "parity.db"
        decaying = _make_lesson(
            key="decay-key", source=LessonSource.observed, ts="2026-01-01T00:00:00+00:00"
        )
        stable = _make_lesson(
            key="stable-key", source=LessonSource.user_stated, ts="2026-01-01T00:00:00+00:00"
        )
        _seed(db_path, decaying, stable)

        shown = {
            r["id"]: r["effective_confidence"]
            for r in show_lessons_typed(
                project=_PROJECT,
                include_legacy=False,
                min_confidence=1,
                limit=100,
                db_path=str(db_path),
            )
        }
        data = _ok_json(
            _run(
                monkeypatch,
                db_path,
                "--project",
                _PROJECT,
                "--key",
                "decay-key",
                "--key",
                "stable-key",
            )
        )
        rows = {r["id"]: r["effective_confidence"] for r in data["rows"]}
        assert rows == shown
        assert rows[decaying.id] < decaying.confidence, "observed 列應已衰減，否則對照無意義"
        assert rows[decaying.id] == decaying.confidence - 3
        assert rows[stable.id] == stable.confidence
