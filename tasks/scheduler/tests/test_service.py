"""測試 service.py：is_due() 各排程類型 + 邊界案例、拓撲排序 + 循環偵測。"""

from datetime import datetime

import pytest

from ..models import JobConfig, Schedule, Weekday
from ..service import get_due_jobs, is_due, resolve_run_order


def _job(
    id: str = "j",
    schedule: Schedule = Schedule.daily,
    time: str = "07:00",
    depends_on: list[str] | None = None,
    **kwargs: object,
) -> JobConfig:
    return JobConfig(
        id=id,
        description="test",
        schedule=schedule,
        time=time,
        command=["echo", id],
        depends_on=depends_on or [],
        **kwargs,
    )


def _last_run(dt: str) -> dict[str, object]:
    return {"started_at": dt, "status": "success"}


class TestIsDue:
    # ── DAILY ──────────────────────────────────────────────────

    def test_daily_never_run(self) -> None:
        job = _job(time="07:00")
        now = datetime(2026, 4, 7, 10, 0)
        assert is_due(job, now, None) is True

    def test_daily_already_run_today(self) -> None:
        job = _job(time="07:00")
        now = datetime(2026, 4, 7, 10, 0)
        last = _last_run("2026-04-07T07:05:00")
        assert is_due(job, now, last) is False

    def test_daily_run_yesterday(self) -> None:
        job = _job(time="07:00")
        now = datetime(2026, 4, 7, 10, 0)
        last = _last_run("2026-04-06T07:05:00")
        assert is_due(job, now, last) is True

    def test_daily_before_scheduled_time(self) -> None:
        job = _job(time="07:00")
        now = datetime(2026, 4, 7, 6, 59)
        assert is_due(job, now, None) is False

    def test_daily_exactly_at_scheduled_time(self) -> None:
        job = _job(time="07:00")
        now = datetime(2026, 4, 7, 7, 0)
        assert is_due(job, now, None) is True

    def test_daily_mac_sleep_catchup(self) -> None:
        """Mac 睡眠補跑：設定 07:00，10:00 才醒，今天尚未跑 → due。"""
        job = _job(time="07:00")
        now = datetime(2026, 4, 7, 10, 0)
        last = _last_run("2026-04-06T07:05:00")  # 昨天跑的
        assert is_due(job, now, last) is True

    # ── WEEKLY ─────────────────────────────────────────────────

    def test_weekly_correct_day_never_run(self) -> None:
        job = _job(schedule=Schedule.weekly, time="07:00", day_of_week=Weekday.tuesday)
        now = datetime(2026, 4, 7, 10, 0)  # 2026-04-07 是 Tuesday
        assert is_due(job, now, None) is True

    def test_weekly_wrong_day(self) -> None:
        job = _job(schedule=Schedule.weekly, time="07:00", day_of_week=Weekday.monday)
        now = datetime(2026, 4, 7, 10, 0)  # Tuesday
        assert is_due(job, now, None) is False

    def test_weekly_already_run_today(self) -> None:
        job = _job(schedule=Schedule.weekly, time="07:00", day_of_week=Weekday.tuesday)
        now = datetime(2026, 4, 7, 10, 0)
        last = _last_run("2026-04-07T07:05:00")
        assert is_due(job, now, last) is False

    # ── QUARTERLY ──────────────────────────────────────────────

    def test_quarterly_correct_month_and_day(self) -> None:
        job = _job(
            schedule=Schedule.quarterly,
            time="08:00",
            months=[1, 4, 7, 10],
            day_of_month=5,
        )
        now = datetime(2026, 4, 5, 9, 0)
        assert is_due(job, now, None) is True

    def test_quarterly_wrong_month(self) -> None:
        job = _job(
            schedule=Schedule.quarterly,
            time="08:00",
            months=[1, 4, 7, 10],
            day_of_month=5,
        )
        now = datetime(2026, 3, 5, 9, 0)
        assert is_due(job, now, None) is False

    def test_quarterly_wrong_day(self) -> None:
        job = _job(
            schedule=Schedule.quarterly,
            time="08:00",
            months=[1, 4, 7, 10],
            day_of_month=5,
        )
        now = datetime(2026, 4, 6, 9, 0)
        assert is_due(job, now, None) is False

    def test_quarterly_already_run_today(self) -> None:
        job = _job(
            schedule=Schedule.quarterly,
            time="08:00",
            months=[1, 4, 7, 10],
            day_of_month=5,
        )
        now = datetime(2026, 4, 5, 9, 0)
        last = _last_run("2026-04-05T08:05:00")
        assert is_due(job, now, last) is False


class TestResolveRunOrder:
    def test_no_dependencies(self) -> None:
        a = _job("a")
        b = _job("b")
        ordered = resolve_run_order([a, b])
        assert {j.id for j in ordered} == {"a", "b"}

    def test_simple_dependency(self) -> None:
        a = _job("a")
        b = _job("b", depends_on=["a"])
        ordered = resolve_run_order([a, b])
        ids = [j.id for j in ordered]
        assert ids.index("a") < ids.index("b")

    def test_chain_dependency(self) -> None:
        a = _job("a")
        b = _job("b", depends_on=["a"])
        c = _job("c", depends_on=["b"])
        ordered = resolve_run_order([c, b, a])
        ids = [j.id for j in ordered]
        assert ids.index("a") < ids.index("b") < ids.index("c")

    def test_circular_dependency_raises(self) -> None:
        a = _job("a", depends_on=["b"])
        b = _job("b", depends_on=["a"])
        with pytest.raises(ValueError, match="循環依賴"):
            resolve_run_order([a, b])

    def test_external_dependency_ignored(self) -> None:
        """depends_on 指向不在 due list 中的 job 時不應影響排序。"""
        b = _job("b", depends_on=["newsletter-extract"])  # 不在此 list
        ordered = resolve_run_order([b])
        assert len(ordered) == 1


class TestGetDueJobs:
    def test_returns_only_enabled_and_due(self) -> None:
        from ..models import ScheduleConfig

        now = datetime(2026, 4, 7, 10, 0)
        j_enabled = _job("enabled", time="07:00")
        j_disabled = JobConfig(
            id="disabled",
            description="d",
            schedule=Schedule.daily,
            time="07:00",
            command=["echo"],
            enabled=False,
        )
        config = ScheduleConfig(jobs=[j_enabled, j_disabled])
        last_runs: dict[str, dict[str, object] | None] = {"enabled": None, "disabled": None}
        due = get_due_jobs(config, last_runs, now)
        assert [j.id for j in due] == ["enabled"]
