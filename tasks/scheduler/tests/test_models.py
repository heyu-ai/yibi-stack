"""測試 models.py：Pydantic 驗證、job type 互斥。"""

import pytest
from pydantic import ValidationError

from ..models import ClaudeJobConfig, JobConfig, Schedule, ScheduleConfig, Weekday


def make_command_job(**kwargs: object) -> JobConfig:
    base: dict[str, object] = {
        "id": "test-job",
        "description": "Test",
        "schedule": Schedule.daily,
        "time": "07:00",
        "command": ["echo", "hi"],
    }
    base.update(kwargs)
    return JobConfig.model_validate(base)


class TestJobConfigValidation:
    def test_valid_command_job(self) -> None:
        job = make_command_job()
        assert job.id == "test-job"
        assert job.command == ["echo", "hi"]

    def test_valid_claude_job(self) -> None:
        job = JobConfig(
            id="claude-job",
            description="d",
            schedule=Schedule.daily,
            time="07:00",
            claude=ClaudeJobConfig(prompt_file="tasks/scheduler/prompts/foo.md"),
        )
        assert job.claude is not None

    def test_valid_skill_job(self) -> None:
        job = JobConfig(
            id="skill-job",
            description="d",
            schedule=Schedule.daily,
            time="07:00",
            skill="icf-global-news-digest",
        )
        assert job.skill == "icf-global-news-digest"

    def test_no_job_type_raises(self) -> None:
        with pytest.raises(ValidationError, match="恰好定義一種"):
            JobConfig(
                id="bad",
                description="d",
                schedule=Schedule.daily,
                time="07:00",
            )

    def test_multiple_job_types_raises(self) -> None:
        with pytest.raises(ValidationError, match="恰好定義一種"):
            JobConfig(
                id="bad",
                description="d",
                schedule=Schedule.daily,
                time="07:00",
                command=["echo"],
                skill="foo",
            )

    def test_invalid_time_format(self) -> None:
        with pytest.raises(ValidationError):
            make_command_job(time="7:00")

    def test_invalid_time_value(self) -> None:
        with pytest.raises(ValidationError):
            make_command_job(time="25:00")

    def test_weekly_requires_day_of_week(self) -> None:
        with pytest.raises(ValidationError, match="day_of_week"):
            make_command_job(schedule=Schedule.weekly)

    def test_weekly_with_day_of_week_ok(self) -> None:
        job = make_command_job(schedule=Schedule.weekly, day_of_week=Weekday.monday)
        assert job.day_of_week == Weekday.monday

    def test_quarterly_requires_months_and_day(self) -> None:
        with pytest.raises(ValidationError, match="day_of_month"):
            make_command_job(schedule=Schedule.quarterly, months=[1, 4, 7, 10])

    def test_time_tuple(self) -> None:
        job = make_command_job(time="07:12")
        assert job.time_tuple == (7, 12)


class TestScheduleConfig:
    def test_job_map(self) -> None:
        job = make_command_job(id="a")
        config = ScheduleConfig(jobs=[job])
        assert "a" in config.job_map()
