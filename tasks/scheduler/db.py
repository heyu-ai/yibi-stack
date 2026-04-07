"""SQLite 資料庫層，儲存 scheduler job 執行歷史。"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .._paths import RUNTIME_DIR
from .models import JobRunStatus

_DEFAULT_DB_PATH = RUNTIME_DIR / "scheduler.db"


class SchedulerDB:
    """Scheduler 執行歷史 SQLite 資料庫。"""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = str(db_path or _DEFAULT_DB_PATH)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def init_db(self) -> None:
        """建立 tables（若不存在）。"""
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS job_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                exit_code INTEGER,
                log_path TEXT,
                error_message TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_job_runs_job_id ON job_runs(job_id);
            CREATE INDEX IF NOT EXISTS idx_job_runs_started_at ON job_runs(started_at);
            """
        )
        self.conn.commit()

    def record_start(self, job_id: str, started_at: str, log_path: str | None = None) -> int:
        """記錄 job 開始執行，回傳 run_id。"""
        cur = self.conn.execute(
            "INSERT INTO job_runs (job_id, started_at, status, log_path) VALUES (?, ?, ?, ?)",
            (job_id, started_at, JobRunStatus.running, log_path),
        )
        self.conn.commit()
        assert cur.lastrowid is not None
        return cur.lastrowid

    def record_finish(
        self,
        run_id: int,
        status: JobRunStatus,
        finished_at: str,
        exit_code: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """更新 job 執行結果。"""
        self.conn.execute(
            "UPDATE job_runs SET status=?, finished_at=?, exit_code=?, error_message=? WHERE id=?",
            (status, finished_at, exit_code, error_message, run_id),
        )
        self.conn.commit()

    def get_last_successful_run(self, job_id: str) -> dict[str, Any] | None:
        """取得最近一次成功執行記錄。"""
        row = self.conn.execute(
            "SELECT * FROM job_runs WHERE job_id=? AND status=? ORDER BY started_at DESC LIMIT 1",
            (job_id, JobRunStatus.success),
        ).fetchone()
        return dict(row) if row else None

    def get_run_history(self, job_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """查詢執行歷史。"""
        if job_id:
            rows = self.conn.execute(
                "SELECT * FROM job_runs WHERE job_id=? ORDER BY started_at DESC LIMIT ?",
                (job_id, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM job_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def cleanup_stale_runs(self, timeout_multiplier: int = 2) -> int:
        """將超時還在 running 狀態的記錄標為 timeout。

        使用 job 預設 timeout 的 multiplier 倍作為判斷門檻，
        避免因 process 崩潰留下殭屍記錄。
        回傳更新的記錄數。
        """
        # 用固定 1 小時作為安全上限（無法從 DB 取得每個 job 的 timeout 設定）
        cutoff_seconds = 3600 * timeout_multiplier
        cur = self.conn.execute(
            """
            UPDATE job_runs
            SET status = ?, error_message = 'cleanup: stale running record'
            WHERE status = ?
              AND (
                CAST((julianday('now') - julianday(started_at)) * 86400 AS INTEGER) > ?
              )
            """,
            (JobRunStatus.timeout, JobRunStatus.running, cutoff_seconds),
        )
        self.conn.commit()
        return cur.rowcount
