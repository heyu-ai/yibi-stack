"""測試 runner.py：mock subprocess 測 command job、mock HTTP 測 claude job。"""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from ..models import ClaudeJobConfig, JobConfig, JobRunStatus, Schedule
from ..runner import _render_prompt, run_job


def _command_job(id: str = "cmd-job") -> JobConfig:
    return JobConfig(
        id=id,
        description="test command",
        schedule=Schedule.daily,
        time="07:00",
        command=["echo", "hello"],
    )


def _claude_job(prompt_file: str) -> JobConfig:
    return JobConfig(
        id="claude-job",
        description="test claude",
        schedule=Schedule.daily,
        time="07:00",
        claude=ClaudeJobConfig(prompt_file=prompt_file),
    )


class TestRenderPrompt:
    def test_replaces_date(self) -> None:
        result = _render_prompt("讀取 {{date}} 的資料", "2026-04-07")
        assert result == "讀取 2026-04-07 的資料"

    def test_multiple_replacements(self) -> None:
        result = _render_prompt("{{date}} start, {{date}} end", "2026-04-07")
        assert result == "2026-04-07 start, 2026-04-07 end"

    def test_no_placeholder(self) -> None:
        result = _render_prompt("no placeholder here", "2026-04-07")
        assert result == "no placeholder here"


class TestRunCommandJob:
    def test_success(self, tmp_path: Path) -> None:
        job = _command_job()
        now = datetime(2026, 4, 7, 7, 0)
        result = run_job(job, tmp_path / "logs", now)
        assert result.status == JobRunStatus.success
        assert result.exit_code == 0
        assert result.log_path is not None

    def test_command_failure(self, tmp_path: Path) -> None:
        job = JobConfig(
            id="fail-job",
            description="test",
            schedule=Schedule.daily,
            time="07:00",
            command=["false"],  # always exits 1
        )
        now = datetime(2026, 4, 7, 7, 0)
        result = run_job(job, tmp_path / "logs", now)
        assert result.status == JobRunStatus.failed
        assert result.exit_code == 1

    def test_log_file_created(self, tmp_path: Path) -> None:
        job = _command_job()
        now = datetime(2026, 4, 7, 7, 0)
        result = run_job(job, tmp_path / "logs", now)
        assert result.log_path is not None
        assert Path(result.log_path).exists()

    def test_sched_eg_001_spawn_failure_reason_is_written_to_the_log(self, tmp_path: Path) -> None:
        """SCHED-EG-001: 執行檔找不到時，**log 檔**必須寫出原因，不只進 DB。

        實測事故（PR #256）：nightly-self-improvement 連 4 晚（7/13～7/16）spawn 失敗，
        DB 的 error_message 有完整答案
        「指令執行失敗（uv）：[Errno 2] No such file or directory: 'uv'」，
        但 log 只寫「status=failed exit_code=1」。log 是人會去看的地方，DB 不是——
        於是這個排程壞了 4 天沒被發現。診斷資訊存在，只是放在沒人看的抽屜裡。

        stdout/stderr 在此都是空的（process 根本沒起來），所以 log 唯一能有的線索
        就是這個 error_message。
        """
        job = JobConfig(
            id="missing-binary-job",
            description="test",
            schedule=Schedule.daily,
            time="21:00",
            command=["definitely-not-installed-xyz", "run"],
        )
        now = datetime(2026, 4, 7, 21, 0)

        result = run_job(job, tmp_path / "logs", now)

        assert result.status == JobRunStatus.failed
        assert result.error_message is not None, "fixture 失效：spawn 應該失敗"
        assert result.log_path is not None
        log_text = Path(result.log_path).read_text(encoding="utf-8")
        assert "definitely-not-installed-xyz" in log_text, (
            f"log 必須說出是哪個執行檔找不到，實際內容：\n{log_text}"
        )
        assert result.error_message in log_text, (
            f"DB 有的 error_message 必須也出現在 log 裡，實際內容：\n{log_text}"
        )


class TestRunClaudeJob:
    def test_acp_gateway_connection_failure(self, tmp_path: Path) -> None:
        """ACP Gateway 未啟動時應記錄錯誤並回傳 exit_code=1。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, dir=tmp_path) as f:
            f.write("測試 prompt {{date}}")
            prompt_path = f.name

        job = _claude_job(prompt_file=prompt_path)

        # Gateway 不在 localhost → URLError
        with patch("tasks.scheduler.runner.PROJECT_ROOT", tmp_path):
            JobConfig(
                id="claude-job",
                description="test",
                schedule=Schedule.daily,
                time="07:00",
                claude=ClaudeJobConfig(prompt_file=Path(prompt_path).name),
            )
            # 直接測試 run_job 對 URLError 的處理
            import urllib.error

            with patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.URLError("connection refused"),
            ):
                # 需要讓 prompt_file 存在
                log_dir = tmp_path / "logs"
                result = run_job(job, log_dir, datetime(2026, 4, 7, 7, 0))

        assert result.status == JobRunStatus.failed
        assert result.exit_code == 1

    def test_prompt_file_not_found(self, tmp_path: Path) -> None:
        job = JobConfig(
            id="claude-job",
            description="test",
            schedule=Schedule.daily,
            time="07:00",
            claude=ClaudeJobConfig(prompt_file="nonexistent/prompt.md"),
        )
        with patch("tasks.scheduler.runner.PROJECT_ROOT", tmp_path):
            result = run_job(job, tmp_path / "logs", datetime(2026, 4, 7, 7, 0))
        assert result.status == JobRunStatus.failed
        assert "不存在" in (result.error_message or "")
