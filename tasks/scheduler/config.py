"""Scheduler 設定檔管理：載入、儲存、生成預設設定。"""

from __future__ import annotations

import json
from pathlib import Path

from .._paths import RUNTIME_DIR
from .models import ClaudeJobConfig, JobConfig, Schedule, ScheduleConfig, Weekday

_DEFAULT_CONFIG_PATH = RUNTIME_DIR / "schedules.json"


def load_config(path: Path | None = None) -> ScheduleConfig:
    """從 .runtime/schedules.json 載入排程設定。"""
    config_path = path or _DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(
            f"排程設定檔不存在：{config_path}\n請先執行：uv run python -m tasks.scheduler setup"
        )
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return ScheduleConfig.model_validate(data)


def save_config(config: ScheduleConfig, path: Path | None = None) -> None:
    """將排程設定寫入 .runtime/schedules.json。"""
    config_path = path or _DEFAULT_CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def generate_default_config() -> ScheduleConfig:
    """生成預設排程設定（5 個 job，newsletter 相關已啟用）。"""
    return ScheduleConfig(
        version="1.0",
        jobs=[
            JobConfig(
                id="newsletter-extract",
                description="擷取 Gmail 電子報",
                schedule=Schedule.daily,
                time="06:57",
                command=[
                    "uv",
                    "run",
                    "python",
                    "-m",
                    "tasks.gmail_newsletter",
                    "run",
                    "--days",
                    "1",
                ],
                enabled=True,
                timeout_seconds=300,
            ),
            JobConfig(
                id="newsletter-digest",
                description="生成每日電子報摘要（Claude via ACP Gateway）",
                schedule=Schedule.daily,
                time="07:12",
                depends_on=["newsletter-extract"],
                claude=ClaudeJobConfig(
                    prompt_file="tasks/scheduler/prompts/newsletter_digest.md",
                ),
                enabled=True,
                timeout_seconds=600,
            ),
            JobConfig(
                id="icf-news-digest",
                description="ICF 全球每週新聞摘要",
                schedule=Schedule.weekly,
                time="07:00",
                day_of_week=Weekday.monday,
                skill="icf-global-news-digest",
                enabled=False,
                timeout_seconds=900,
            ),
            JobConfig(
                id="billing-import",
                description="每季帳單 PDF 匯入",
                schedule=Schedule.quarterly,
                time="08:00",
                months=[1, 4, 7, 10],
                day_of_month=5,
                command=["uv", "run", "python", "-m", "tasks.gmail_billing", "run", "--days", "95"],
                enabled=False,
                timeout_seconds=1800,
            ),
            JobConfig(
                id="einvoice-blank-upload",
                description="空白發票號碼上傳（雙月）",
                schedule=Schedule.bimonthly,
                time="09:00",
                months=[1, 3, 5, 7, 9, 11],
                day_of_month=10,
                skill="einvoice-blank-upload",
                enabled=False,
                timeout_seconds=600,
            ),
        ],
    )
