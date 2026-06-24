"""Scheduler CLI：setup, tick, status, history, run-job, install, uninstall。"""

from __future__ import annotations

import subprocess  # nosec B404 — launchctl 管理需要 subprocess
import textwrap
from datetime import datetime
from pathlib import Path

import click

from .._paths import PROJECT_ROOT, RUNTIME_DIR
from .config import generate_default_config, load_config, save_config
from .db import SchedulerDB
from .models import JobRunStatus
from .runner import run_job
from .service import get_due_jobs

_LOG_DIR = RUNTIME_DIR / "logs"
_DB_PATH = RUNTIME_DIR / "scheduler.db"
_CONFIG_PATH = RUNTIME_DIR / "schedules.json"
_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / "com.howie.ainization-scheduler.plist"
_PLIST_LABEL = "com.howie.ainization-scheduler"


@click.group()
def cli() -> None:
    """Skill Scheduler — 定期自動執行 skill 的排程管理工具。"""


@cli.command()
def setup() -> None:
    """初始化排程設定與資料庫（首次使用時執行）。"""
    if _CONFIG_PATH.exists():
        click.echo(f"設定檔已存在：{_CONFIG_PATH}（跳過生成）")
    else:
        config = generate_default_config()
        save_config(config, _CONFIG_PATH)
        click.echo(f"已生成預設設定：{_CONFIG_PATH}")

    db = SchedulerDB(_DB_PATH)
    db.init_db()
    db.close()
    click.echo(f"已初始化資料庫：{_DB_PATH}")
    click.echo("\n下一步：")
    click.echo("  1. 編輯 .runtime/schedules.json 調整排程")
    click.echo("  2. uv run python -m tasks.scheduler status  # 查看 job 狀態")
    click.echo("  3. uv run python -m tasks.scheduler install # 安裝 LaunchAgent")


@cli.command()
@click.option("--dry-run", is_flag=True, help="只列出 due jobs，不實際執行")
def tick(dry_run: bool) -> None:
    """檢查並執行到期的 jobs（由 LaunchAgent 每 60 秒呼叫）。"""
    try:
        config = load_config(_CONFIG_PATH)
    except FileNotFoundError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1) from None

    db = SchedulerDB(_DB_PATH)
    db.init_db()
    db.cleanup_stale_runs()

    now = datetime.now()
    last_runs = {j.id: db.get_last_run(j.id) for j in config.jobs if j.enabled}
    due_jobs = get_due_jobs(config, last_runs, now)

    if not due_jobs:
        return  # 沒事做，靜默退出（LaunchAgent 每 60 秒跑，大部分時候走這裡）

    if dry_run:
        click.echo(f"[dry-run] Due jobs at {now.strftime('%H:%M')}:")
        for job in due_jobs:
            click.echo(f"  - {job.id}")
        return

    # 依拓撲順序循序執行
    completed_ok: set[str] = set()
    due_ids = {j.id for j in due_jobs}
    for job in due_jobs:
        failed_deps = [dep for dep in job.depends_on if dep in due_ids and dep not in completed_ok]
        if failed_deps:
            click.echo(f"[skip] {job.id} — dependency 失敗：{failed_deps}")
            run_id = db.record_start(job.id, now.isoformat())
            db.record_finish(
                run_id,
                JobRunStatus.skipped,
                datetime.now().isoformat(),
                error_message=f"deps failed: {failed_deps}",
            )
            continue

        click.echo(f"[run] {job.id} ...")
        run_id = db.record_start(job.id, now.isoformat(), str(_LOG_DIR / f"{job.id}.log"))
        result = run_job(job, _LOG_DIR, now)
        db.record_finish(
            run_id,
            result.status,
            result.finished_at or datetime.now().isoformat(),
            result.exit_code,
            result.error_message,
        )

        if result.status == JobRunStatus.success:
            completed_ok.add(job.id)
            click.echo(f"[ok]  {job.id}")
        else:
            err = result.error_message or f"exit_code={result.exit_code}"
            click.echo(f"[err] {job.id} — {err}")

    db.close()


@cli.command()
def status() -> None:
    """顯示所有 job 的排程與最後執行狀態。"""
    try:
        config = load_config(_CONFIG_PATH)
    except FileNotFoundError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1) from None

    db = SchedulerDB(_DB_PATH)
    db.init_db()

    header = f"{'ID':<28} {'SCHEDULE':<12} {'TIME':<6} {'ENABLED':<8} {'LAST RUN':<20} STATUS"
    click.echo(header)
    click.echo("-" * 90)
    for job in config.jobs:
        last_time = "never"
        last_status = "-"
        history = db.get_run_history(job.id, limit=1)
        if history:
            last_time = history[0]["started_at"][:16]
            last_status = history[0]["status"]

        enabled_str = "✓" if job.enabled else "✗"
        row = (
            f"{job.id:<28} {job.schedule:<12} {job.time:<6} "
            f"{enabled_str:<8} {last_time:<20} {last_status}"
        )
        click.echo(row)

    db.close()


@cli.command()
@click.option("--job-id", default=None, help="過濾特定 job")
@click.option("--limit", default=20, show_default=True, help="顯示最多幾筆")
def history(job_id: str | None, limit: int) -> None:
    """顯示執行歷史。"""
    db = SchedulerDB(_DB_PATH)
    db.init_db()
    rows = db.get_run_history(job_id, limit)
    db.close()

    if not rows:
        click.echo("無執行記錄。")
        return

    click.echo(f"{'ID':<6} {'JOB ID':<28} {'STARTED':<20} {'STATUS':<10} EXIT")
    click.echo("-" * 75)
    for row in rows:
        click.echo(
            f"{row['id']:<6} {row['job_id']:<28} {row['started_at'][:19]:<20} "
            f"{row['status']:<10} {row.get('exit_code', '-')}"
        )


@cli.command("run-job")
@click.argument("job_id")
def run_job_cmd(job_id: str) -> None:
    """強制立刻執行某 job（忽略 is_due 判斷）。"""
    try:
        config = load_config(_CONFIG_PATH)
    except FileNotFoundError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1) from None

    job_map = config.job_map()
    if job_id not in job_map:
        click.echo(f"找不到 job：{job_id}", err=True)
        click.echo(f"可用 jobs：{', '.join(job_map)}")
        raise SystemExit(1)

    job = job_map[job_id]
    db = SchedulerDB(_DB_PATH)
    db.init_db()
    now = datetime.now()

    click.echo(f"[run] {job.id} ...")
    run_id = db.record_start(job.id, now.isoformat())
    result = run_job(job, _LOG_DIR, now)
    db.record_finish(
        run_id,
        result.status,
        result.finished_at or datetime.now().isoformat(),
        result.exit_code,
        result.error_message,
    )
    db.close()

    if result.status == JobRunStatus.success:
        click.echo(f"[ok]  {job.id} — log: {result.log_path}")
    else:
        err = result.error_message or f"exit_code={result.exit_code}"
        click.echo(f"[err] {job.id} — {err}")
        click.echo(f"      log: {result.log_path}")
        raise SystemExit(1)


@cli.command()
def install() -> None:
    """生成並載入 macOS LaunchAgent（每 60 秒執行 tick）。"""
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if not venv_python.exists():
        click.echo("找不到 .venv/bin/python，請先執行：uv sync", err=True)
        raise SystemExit(1)

    # 確保 DB + config 已初始化
    db = SchedulerDB(_DB_PATH)
    db.init_db()
    db.close()
    if not _CONFIG_PATH.exists():
        config = generate_default_config()
        save_config(config, _CONFIG_PATH)
        click.echo(f"已生成預設設定：{_CONFIG_PATH}")

    home = str(Path.home())
    path_env = f"{home}/.local/bin:{home}/.cargo/bin:/usr/local/bin:/usr/bin:/bin"
    plist_content = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
            "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>{_PLIST_LABEL}</string>
            <key>ProgramArguments</key>
            <array>
                <string>{venv_python}</string>
                <string>-m</string>
                <string>tasks.scheduler</string>
                <string>tick</string>
            </array>
            <key>WorkingDirectory</key>
            <string>{PROJECT_ROOT}</string>
            <key>EnvironmentVariables</key>
            <dict>
                <key>PATH</key>
                <string>{path_env}</string>
                <key>HOME</key>
                <string>{home}</string>
            </dict>
            <key>StartInterval</key>
            <integer>60</integer>
            <key>RunAtLoad</key>
            <true/>
            <key>KeepAlive</key>
            <false/>
            <key>StandardOutPath</key>
            <string>/tmp/ainization-scheduler.log</string>
            <key>StandardErrorPath</key>
            <string>/tmp/ainization-scheduler.err</string>
        </dict>
        </plist>
    """)

    _PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PLIST_PATH.write_text(plist_content, encoding="utf-8")
    click.echo(f"已寫入：{_PLIST_PATH}")

    # 卸載舊的（若存在），再載入新的
    subprocess.run(  # nosec B603 B607
        ["launchctl", "unload", str(_PLIST_PATH)], capture_output=True
    )
    lc_result = subprocess.run(  # nosec B603 B607
        ["launchctl", "load", str(_PLIST_PATH)], capture_output=True, text=True
    )
    if lc_result.returncode == 0:
        click.echo(f"LaunchAgent 已載入：{_PLIST_LABEL}")
        click.echo("每 60 秒自動 tick，log：/tmp/ainization-scheduler.log")
    else:
        click.echo(f"launchctl load 失敗：{lc_result.stderr}", err=True)
        raise SystemExit(1)


@cli.command()
def uninstall() -> None:
    """卸載並刪除 LaunchAgent。"""
    if not _PLIST_PATH.exists():
        click.echo("LaunchAgent 不存在，跳過。")
        return

    subprocess.run(  # nosec B603 B607
        ["launchctl", "unload", str(_PLIST_PATH)], capture_output=True
    )
    _PLIST_PATH.unlink()
    click.echo(f"已卸載並刪除：{_PLIST_PATH}")
