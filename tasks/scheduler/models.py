"""Scheduler 資料模型。"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, field_validator, model_validator


class Schedule(StrEnum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    bimonthly = "bimonthly"
    quarterly = "quarterly"


class Weekday(StrEnum):
    monday = "monday"
    tuesday = "tuesday"
    wednesday = "wednesday"
    thursday = "thursday"
    friday = "friday"
    saturday = "saturday"
    sunday = "sunday"

    def to_weekday_int(self) -> int:
        return list(Weekday).index(self)


class ClaudeJobConfig(BaseModel):
    """ACP Gateway 呼叫設定（model/tools 由 sandbox 管理）。"""

    prompt_file: str
    timeout_ms: int | None = None


class JobConfig(BaseModel):
    id: str
    description: str
    schedule: Schedule
    time: str  # HH:MM
    day_of_week: Weekday | None = None
    day_of_month: int | None = None
    months: list[int] | None = None
    command: list[str] | None = None
    claude: ClaudeJobConfig | None = None
    skill: str | None = None
    depends_on: list[str] = []
    enabled: bool = True
    timeout_seconds: int = 300

    @field_validator("time")
    @classmethod
    def validate_time(cls, v: str) -> str:
        if not re.match(r"^\d{2}:\d{2}$", v):
            raise ValueError(f"time 格式必須是 HH:MM，收到：{v!r}")
        hh, mm = int(v[:2]), int(v[3:])
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError(f"無效時間：{v!r}")
        return v

    @field_validator("day_of_month")
    @classmethod
    def validate_day_of_month(cls, v: int | None) -> int | None:
        if v is not None and not 1 <= v <= 31:
            raise ValueError(f"day_of_month 必須在 1-31，收到：{v}")
        return v

    @field_validator("months")
    @classmethod
    def validate_months(cls, v: list[int] | None) -> list[int] | None:
        if v is not None:
            for m in v:
                if not 1 <= m <= 12:
                    raise ValueError(f"months 中有無效月份：{m}")
        return v

    @model_validator(mode="after")
    def validate_job_type(self) -> JobConfig:
        defined = sum([self.command is not None, self.claude is not None, self.skill is not None])
        if defined != 1:
            raise ValueError(
                f"job '{self.id}' 必須恰好定義一種執行方式"
                f"（command/claude/skill），目前定義了 {defined} 種"
            )
        return self

    @model_validator(mode="after")
    def validate_schedule_fields(self) -> JobConfig:
        if self.schedule == Schedule.weekly and self.day_of_week is None:
            raise ValueError(f"job '{self.id}' schedule=weekly 時必須指定 day_of_week")
        if self.schedule in (Schedule.monthly, Schedule.bimonthly, Schedule.quarterly):
            if self.day_of_month is None:
                raise ValueError(
                    f"job '{self.id}' schedule={self.schedule} 時必須指定 day_of_month"
                )
            if self.months is None:
                raise ValueError(f"job '{self.id}' schedule={self.schedule} 時必須指定 months")
        return self

    @property
    def time_tuple(self) -> tuple[int, int]:
        """回傳 (hour, minute)。"""
        return int(self.time[:2]), int(self.time[3:])


class ScheduleConfig(BaseModel):
    version: str = "1.0"
    jobs: list[JobConfig] = []

    def job_map(self) -> dict[str, JobConfig]:
        return {j.id: j for j in self.jobs}


class JobRunStatus(StrEnum):
    running = "running"
    success = "success"
    failed = "failed"
    skipped = "skipped"
    timeout = "timeout"


class JobRun(BaseModel):
    id: int | None = None
    job_id: str
    started_at: str
    finished_at: str | None = None
    status: JobRunStatus
    exit_code: int | None = None
    log_path: str | None = None
    error_message: str | None = None

    def model_post_init(self, __context: Any) -> None:
        pass
