"""Scheduler 核心邏輯：排程判斷、拓撲排序、tick 主流程。"""

from __future__ import annotations

from collections import deque
from datetime import datetime, time
from typing import Any

from .models import JobConfig, Schedule, ScheduleConfig


def is_due(job: JobConfig, now: datetime, last_run: dict[str, Any] | None) -> bool:
    """判斷 job 是否到了執行時間。

    設計原則：
    - 比較日期而非精確時間，支援 Mac 睡眠後補跑（設定 07:00，10:00 才醒來且今天尚未
      *嘗試*過 → 判為 due）。
    - 以最後一次*嘗試*（任何狀態：success / failed / running）為準，而非僅最後一次
      *成功*。同一排程週期內已嘗試過就不再 due，避免失敗 job 每個 tick 重試
      （retry-storm）；失敗的 job 會等到下一個排程週期才重跑。
    """
    hour, minute = job.time_tuple
    scheduled_time = time(hour, minute)
    now_time = now.time().replace(second=0, microsecond=0)

    # 時間未到，直接 false
    if now_time < scheduled_time:
        return False

    # 解析上次嘗試時間（任何狀態）
    last_run_dt: datetime | None = None
    if last_run:
        last_run_dt = datetime.fromisoformat(last_run["started_at"])

    match job.schedule:
        case Schedule.daily:
            if last_run_dt is None:
                return True
            return last_run_dt.date() < now.date()

        case Schedule.weekly:
            if job.day_of_week is None:
                return False
            target_weekday = job.day_of_week.to_weekday_int()
            if now.weekday() != target_weekday:
                return False
            if last_run_dt is None:
                return True
            return last_run_dt.date() < now.date()

        case Schedule.monthly | Schedule.bimonthly | Schedule.quarterly:
            if job.months is None or job.day_of_month is None:
                return False
            if now.month not in job.months:
                return False
            if now.day != job.day_of_month:
                return False
            if last_run_dt is None:
                return True
            # 同月同日已嘗試過
            return not (
                last_run_dt.year == now.year
                and last_run_dt.month == now.month
                and last_run_dt.day == now.day
            )

    return False  # pragma: no cover


def resolve_run_order(jobs: list[JobConfig]) -> list[JobConfig]:
    """拓撲排序 jobs，依 depends_on 決定執行順序。

    使用 Kahn's algorithm（BFS）。若偵測到循環依賴則 raise ValueError。
    """
    job_map = {j.id: j for j in jobs}
    in_degree: dict[str, int] = {j.id: 0 for j in jobs}
    dependents: dict[str, list[str]] = {j.id: [] for j in jobs}

    for job in jobs:
        for dep in job.depends_on:
            if dep in job_map:
                in_degree[job.id] += 1
                dependents[dep].append(job.id)

    queue: deque[str] = deque(jid for jid, deg in in_degree.items() if deg == 0)
    ordered: list[JobConfig] = []

    while queue:
        jid = queue.popleft()
        ordered.append(job_map[jid])
        for dependent_id in dependents[jid]:
            in_degree[dependent_id] -= 1
            if in_degree[dependent_id] == 0:
                queue.append(dependent_id)

    if len(ordered) != len(jobs):
        cycle_ids = [jid for jid, deg in in_degree.items() if deg > 0]
        raise ValueError(f"偵測到循環依賴，涉及 jobs：{cycle_ids}")

    return ordered


def get_due_jobs(
    config: ScheduleConfig,
    db_last_runs: dict[str, dict[str, Any] | None],
    now: datetime,
) -> list[JobConfig]:
    """回傳目前 due 且 enabled 的 jobs，已做拓撲排序。"""
    enabled = [j for j in config.jobs if j.enabled]
    due = [j for j in enabled if is_due(j, now, db_last_runs.get(j.id))]
    if not due:
        return []
    return resolve_run_order(due)
