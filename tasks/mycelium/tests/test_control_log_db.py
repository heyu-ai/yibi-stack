"""Control log DB 層測試（CTL-DB-001~004）。"""

from tasks.mycelium.db import AgentsDB
from tasks.mycelium.models import ControlLogCategory, ControlLogEntry, ControlLogSession


def make_entry(**kwargs: object) -> ControlLogEntry:
    defaults: dict[str, object] = {
        "pr_number": 42,
        "category": ControlLogCategory.autonomous_decision,
        "summary": "Chose SQLite WAL mode",
        "user_requested": 0,
    }
    return ControlLogEntry(**{**defaults, **kwargs})


class TestControlLogDB:
    def test_ctl_db_001_tables_exist_after_init(self) -> None:
        """CTL-DB-001: init_db() 建立 control_log_entries 與 control_log_sessions 兩個 table。"""
        db = AgentsDB(":memory:")
        db.init_db()
        cur = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'control_log%'"
        )
        names = {row["name"] for row in cur.fetchall()}
        assert "control_log_entries" in names
        assert "control_log_sessions" in names
        db.close()

    def test_ctl_db_002_idempotent_init(self) -> None:
        """CTL-DB-002: init_db() 可安全呼叫兩次，不拋例外、不重複建表。"""
        db = AgentsDB(":memory:")
        db.init_db()
        db.init_db()
        cur = db.conn.execute(
            "SELECT COUNT(*) AS c FROM sqlite_master"
            " WHERE type='table' AND name='control_log_entries'"
        )
        assert cur.fetchone()["c"] == 1
        db.close()

    def test_ctl_db_003_insert_and_query_entry(self) -> None:
        """CTL-DB-003: insert_control_log_entry 後可 query_control_log_entries 查到。"""
        db = AgentsDB(":memory:")
        db.init_db()
        entry = make_entry(pr_number=42, summary="test decision")
        new_id = db.insert_control_log_entry(entry)
        assert isinstance(new_id, int)
        assert new_id > 0

        rows = db.query_control_log_entries(pr_number=42)
        assert len(rows) == 1
        assert rows[0]["summary"] == "test decision"
        assert rows[0]["category"] == "autonomous_decision"
        assert rows[0]["pr_number"] == 42
        db.close()

    def test_ctl_db_004_indexes_exist(self) -> None:
        """CTL-DB-004: idx_ctl_entries_pr / created_at / category 三個索引存在。"""
        db = AgentsDB(":memory:")
        db.init_db()
        cur = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_ctl_%'"
        )
        names = {row["name"] for row in cur.fetchall()}
        assert "idx_ctl_entries_pr" in names
        assert "idx_ctl_entries_created_at" in names
        assert "idx_ctl_entries_category" in names
        db.close()

    def test_ctl_db_005_insert_control_log_session(self) -> None:
        """CTL-DB-005: insert_control_log_session 寫入並回傳正整數 id。"""
        db = AgentsDB(":memory:")
        db.init_db()
        session = ControlLogSession(pr_number=10, autonomy_ratio=0.5, total_entries=3)
        new_id = db.insert_control_log_session(session)
        assert isinstance(new_id, int)
        assert new_id > 0
        cur = db.conn.execute("SELECT * FROM control_log_sessions WHERE id = ?", (new_id,))
        row = cur.fetchone()
        assert row["pr_number"] == 10
        assert row["autonomy_ratio"] == 0.5
        assert row["total_entries"] == 3
        db.close()
