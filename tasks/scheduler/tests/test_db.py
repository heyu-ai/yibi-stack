"""測試 db.py：record_start/finish、get_last_successful_run、cleanup_stale_runs。"""

from pathlib import Path

import pytest

from ..db import SchedulerDB
from ..models import JobRunStatus


@pytest.fixture
def db(tmp_path: Path) -> SchedulerDB:
    instance = SchedulerDB(tmp_path / "test_scheduler.db")
    instance.init_db()
    return instance


class TestSchedulerDB:
    def test_record_start_returns_id(self, db: SchedulerDB) -> None:
        run_id = db.record_start("test-job", "2026-04-07T07:00:00")
        assert run_id == 1

    def test_record_finish_updates_status(self, db: SchedulerDB) -> None:
        run_id = db.record_start("test-job", "2026-04-07T07:00:00")
        db.record_finish(run_id, JobRunStatus.success, "2026-04-07T07:01:00", exit_code=0)

        history = db.get_run_history("test-job", limit=1)
        assert history[0]["status"] == "success"
        assert history[0]["exit_code"] == 0

    def test_get_last_successful_run_none_when_no_runs(self, db: SchedulerDB) -> None:
        result = db.get_last_successful_run("nonexistent")
        assert result is None

    def test_get_last_successful_run_returns_latest_success(self, db: SchedulerDB) -> None:
        run_id = db.record_start("job-a", "2026-04-06T07:00:00")
        db.record_finish(run_id, JobRunStatus.success, "2026-04-06T07:01:00", exit_code=0)

        run_id2 = db.record_start("job-a", "2026-04-07T07:00:00")
        db.record_finish(run_id2, JobRunStatus.success, "2026-04-07T07:01:00", exit_code=0)

        last = db.get_last_successful_run("job-a")
        assert last is not None
        assert last["started_at"] == "2026-04-07T07:00:00"

    def test_get_last_successful_run_ignores_failed(self, db: SchedulerDB) -> None:
        run_id = db.record_start("job-b", "2026-04-07T07:00:00")
        db.record_finish(run_id, JobRunStatus.failed, "2026-04-07T07:01:00", exit_code=1)

        last = db.get_last_successful_run("job-b")
        assert last is None

    def test_get_last_run_none_when_no_runs(self, db: SchedulerDB) -> None:
        assert db.get_last_run("nonexistent") is None

    def test_get_last_run_returns_latest_regardless_of_status(self, db: SchedulerDB) -> None:
        # 先成功，後失敗 → get_last_run 應回傳最新（失敗）那筆
        ok = db.record_start("job-c", "2026-04-06T07:00:00")
        db.record_finish(ok, JobRunStatus.success, "2026-04-06T07:01:00", exit_code=0)
        bad = db.record_start("job-c", "2026-04-07T07:00:00")
        db.record_finish(bad, JobRunStatus.failed, "2026-04-07T07:01:00", exit_code=1)

        last = db.get_last_run("job-c")
        assert last is not None
        assert last["started_at"] == "2026-04-07T07:00:00"
        assert last["status"] == JobRunStatus.failed
        # 對照：get_last_successful_run 仍只回傳成功那筆
        ok_last = db.get_last_successful_run("job-c")
        assert ok_last is not None
        assert ok_last["started_at"] == "2026-04-06T07:00:00"

    def test_get_run_history_all_jobs(self, db: SchedulerDB) -> None:
        for job_id in ["job-a", "job-b"]:
            run_id = db.record_start(job_id, "2026-04-07T07:00:00")
            db.record_finish(run_id, JobRunStatus.success, "2026-04-07T07:01:00", exit_code=0)

        history = db.get_run_history(limit=10)
        assert len(history) == 2

    def test_cleanup_stale_runs(self, db: SchedulerDB) -> None:
        # 插入一個 2 天前 still-running 的記錄
        db.record_start("stale-job", "2024-01-01T00:00:00")

        updated = db.cleanup_stale_runs(timeout_multiplier=1)
        assert updated == 1

        history = db.get_run_history("stale-job", limit=1)
        assert history[0]["status"] == "timeout"

    def test_cleanup_does_not_affect_recent_running(self, db: SchedulerDB) -> None:
        from datetime import datetime

        now = datetime.now().isoformat()
        db.record_start("fresh-job", now)

        updated = db.cleanup_stale_runs(timeout_multiplier=1)
        assert updated == 0
